from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .auth import DUMMY_PASSWORD_HASH, create_access_token, hash_refresh_token, new_refresh_token, verify_password
from .config import get_settings
from .dependencies import CurrentTenant, CurrentUser, DbSession, ReviewerMembership, unauthorized
from .models import Document, Membership, RefreshSession, User, utcnow
from .schemas import (
    DocumentOut,
    LoginRequest,
    LoginResponse,
    PaginatedJobs,
    ReviewJobOut,
    TenantMembershipOut,
    UploadResponse,
    UserOut,
)
from .services import create_document_and_job, get_tenant_document, get_tenant_job, list_jobs, new_review_job, retry_job


router = APIRouter(prefix="/api/v1")
REFRESH_COOKIE = "review_refresh_token"


def issue_refresh_session(db: DbSession, response: Response, user: User) -> None:
    settings = get_settings()
    token, token_hash = new_refresh_token()
    expires_at = utcnow() + timedelta(days=settings.refresh_token_days)
    db.add(RefreshSession(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    db.commit()
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )


def tenant_memberships(db: DbSession, user_id: str) -> list[TenantMembershipOut]:
    memberships = db.scalars(
        select(Membership)
        .options(joinedload(Membership.tenant))
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at, Membership.id)
    )
    return [
        TenantMembershipOut(
            id=membership.tenant.id,
            name=membership.tenant.name,
            slug=membership.tenant.slug,
            role=membership.role,
        )
        for membership in memberships
    ]


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, db: DbSession):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    password_matches = verify_password(payload.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if user is None or not user.is_active or not password_matches:
        raise unauthorized("Invalid email or password")
    result = LoginResponse(
        access_token=create_access_token(user),
        user=user,
        tenants=tenant_memberships(db, user.id),
    )
    issue_refresh_session(db, response, user)
    return result


@router.post("/auth/refresh", response_model=LoginResponse)
def refresh_access_token(
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
):
    if not refresh_token:
        raise unauthorized("Refresh session required")
    session = db.scalar(
        select(RefreshSession)
        .options(joinedload(RefreshSession.user))
        .where(
            RefreshSession.token_hash == hash_refresh_token(refresh_token),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > utcnow(),
        )
        .with_for_update()
    )
    if session is None or not session.user.is_active:
        raise unauthorized("Invalid or expired refresh session")
    session.revoked_at = utcnow()
    db.flush()
    issue_refresh_session(db, response, session.user)
    return LoginResponse(
        access_token=create_access_token(session.user),
        user=session.user,
        tenants=tenant_memberships(db, session.user.id),
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
):
    if refresh_token:
        session = db.scalar(
            select(RefreshSession)
            .where(
                RefreshSession.token_hash == hash_refresh_token(refresh_token),
                RefreshSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if session is not None:
            session.revoked_at = utcnow()
            db.commit()
    response.delete_cookie(key=REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.get("/tenants", response_model=list[TenantMembershipOut])
def tenants(user: CurrentUser, db: DbSession):
    return [membership for membership in tenant_memberships(db, user.id)]


@router.post("/documents", response_model=UploadResponse, status_code=201)
def upload_document(
    db: DbSession,
    tenant: CurrentTenant,
    user: CurrentUser,
    _: ReviewerMembership,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
):
    document, job = create_document_and_job(db, tenant, user, file, idempotency_key=idempotency_key)
    job.document = document
    return UploadResponse(document=document, review_job=job)


@router.get("/documents", response_model=list[DocumentOut])
def documents(db: DbSession, tenant: CurrentTenant):
    return list(
        db.scalars(
            select(Document).where(Document.tenant_id == tenant.id).order_by(Document.created_at.desc()).limit(100)
        )
    )


@router.get("/documents/{document_id}/download")
def download_document(document_id: str, db: DbSession, tenant: CurrentTenant):
    document = get_tenant_document(db, tenant.id, document_id)
    if not Path(document.storage_path).is_file():
        raise HTTPException(status_code=404, detail="Document file not found")
    return FileResponse(
        document.storage_path,
        media_type=document.content_type,
        filename=document.filename,
    )


@router.post("/documents/{document_id}/reviews", response_model=ReviewJobOut, status_code=201)
def create_review(document_id: str, db: DbSession, tenant: CurrentTenant, _: ReviewerMembership):
    document = get_tenant_document(db, tenant.id, document_id)
    job = new_review_job(tenant.id, document.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    job.document = document
    return job


@router.get("/review-jobs", response_model=PaginatedJobs)
def review_jobs(
    db: DbSession,
    tenant: CurrentTenant,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = list_jobs(db, tenant.id, page, page_size)
    return PaginatedJobs(items=items, total=total, page=page, page_size=page_size)


@router.get("/review-jobs/{job_id}", response_model=ReviewJobOut)
def review_job(job_id: str, db: DbSession, tenant: CurrentTenant):
    return get_tenant_job(db, tenant.id, job_id)


@router.post("/review-jobs/{job_id}/retry", response_model=ReviewJobOut, status_code=201)
def retry_review_job(job_id: str, db: DbSession, tenant: CurrentTenant, _: ReviewerMembership):
    return retry_job(db, tenant.id, job_id)
