import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .config import get_settings
from .document_text import DocumentExtractionError, validate_filename
from .models import Document, IdempotencyKey, JobStatus, ReviewJob, Tenant, User, utcnow


def new_review_job(
    tenant_id: str,
    document_id: str,
    retry_of: ReviewJob | None = None,
    available_at: datetime | None = None,
) -> ReviewJob:
    job_id = str(uuid.uuid4())
    return ReviewJob(
        id=job_id,
        tenant_id=tenant_id,
        document_id=document_id,
        retry_of_job_id=retry_of.id if retry_of else None,
        root_job_id=retry_of.root_job_id if retry_of else job_id,
        attempts=retry_of.attempts if retry_of else 0,
        max_attempts=retry_of.max_attempts if retry_of else 3,
        available_at=available_at or utcnow(),
    )


def create_document_and_job(
    db: Session,
    tenant: Tenant,
    user: User,
    upload: UploadFile,
    idempotency_key: str | None = None,
) -> tuple[Document, ReviewJob]:
    settings = get_settings()
    data = upload.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large")

    filename = upload.filename or "document.txt"
    try:
        suffix = validate_filename(filename)
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    fingerprint = hashlib.sha256(data).hexdigest()
    normalized_key = idempotency_key.strip() if idempotency_key else None
    if idempotency_key is not None and not normalized_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key cannot be empty")
    if normalized_key:
        existing = _idempotent_upload(db, tenant.id, normalized_key, fingerprint)
        if existing:
            return existing
    document_id = str(uuid.uuid4())
    tenant_dir = settings.upload_dir / tenant.id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    storage_path = tenant_dir / f"{document_id}{suffix}"
    storage_path.write_bytes(data)

    document = Document(
        id=document_id,
        tenant_id=tenant.id,
        created_by_user_id=user.id,
        filename=Path(filename).name,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=len(data),
        storage_path=str(storage_path),
        content_text=None,
    )
    job = new_review_job(tenant.id, document.id)
    job.document = document
    db.add_all([document, job])
    if normalized_key:
        db.add(
            IdempotencyKey(
                tenant_id=tenant.id,
                key=normalized_key,
                content_fingerprint=fingerprint,
                document_id=document.id,
                review_job_id=job.id,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        storage_path.unlink(missing_ok=True)
        if normalized_key:
            existing = _idempotent_upload(db, tenant.id, normalized_key, fingerprint)
            if existing:
                return existing
        raise
    except Exception:
        db.rollback()
        storage_path.unlink(missing_ok=True)
        raise
    db.refresh(document)
    db.refresh(job)
    return document, job


def _idempotent_upload(
    db: Session,
    tenant_id: str,
    key: str,
    fingerprint: str,
) -> tuple[Document, ReviewJob] | None:
    record = db.scalar(
        select(IdempotencyKey).where(IdempotencyKey.tenant_id == tenant_id, IdempotencyKey.key == key)
    )
    if record is None:
        return None
    if record.content_fingerprint != fingerprint:
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used for different content")
    document = db.get(Document, record.document_id)
    job = db.scalar(
        select(ReviewJob)
        .options(joinedload(ReviewJob.document))
        .where(ReviewJob.id == record.review_job_id, ReviewJob.tenant_id == tenant_id)
    )
    if document is None or job is None:
        raise HTTPException(status_code=409, detail="Idempotent upload record is no longer available")
    job.document = document
    return document, job


def get_tenant_document(db: Session, tenant_id: str, document_id: str) -> Document:
    document = db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def get_tenant_job(db: Session, tenant_id: str, job_id: str) -> ReviewJob:
    job = db.scalar(
        select(ReviewJob)
        .options(joinedload(ReviewJob.document))
        .where(ReviewJob.id == job_id, ReviewJob.tenant_id == tenant_id)
    )
    if not job:
        raise HTTPException(status_code=404, detail="Review job not found")
    return job


def list_jobs(db: Session, tenant_id: str, page: int, page_size: int) -> tuple[list[ReviewJob], int]:
    predicate = ReviewJob.tenant_id == tenant_id
    total = db.scalar(select(func.count()).select_from(ReviewJob).where(predicate)) or 0
    items = list(
        db.scalars(
            select(ReviewJob)
            .options(joinedload(ReviewJob.document))
            .where(predicate)
            .order_by(ReviewJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return items, total


def retry_job(db: Session, tenant_id: str, job_id: str) -> ReviewJob:
    job = get_tenant_job(db, tenant_id, job_id)
    if job.status != JobStatus.failed:
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried")
    if job.attempts >= job.max_attempts:
        raise HTTPException(status_code=409, detail="Maximum retry attempts reached")
    if db.scalar(select(ReviewJob.id).where(ReviewJob.retry_of_job_id == job.id)):
        raise HTTPException(status_code=409, detail="A retry job already exists")
    retry = new_review_job(tenant_id, job.document_id, retry_of=job)
    retry.document = job.document
    db.add(retry)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A retry job already exists") from exc
    db.refresh(retry)
    return retry
