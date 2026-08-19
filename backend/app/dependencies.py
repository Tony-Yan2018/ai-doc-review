from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import decode_access_token
from .database import get_db
from .models import Membership, MembershipRole, Tenant, User


DbSession = Annotated[Session, Depends(get_db)]
bearer_scheme = HTTPBearer(auto_error=False)


def unauthorized(detail: str = "Invalid or expired access token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("Authentication required")
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise unauthorized() from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_membership(
    db: DbSession,
    user: CurrentUser,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> Membership:
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant_id)
    )
    if membership is None:
        # Do not disclose whether a tenant outside the user's memberships exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return membership


CurrentMembership = Annotated[Membership, Depends(get_current_membership)]


def get_current_tenant(
    membership: CurrentMembership,
) -> Tenant:
    return membership.tenant


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]


def require_reviewer(membership: CurrentMembership) -> Membership:
    if membership.role == MembershipRole.viewer:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer role required")
    return membership


ReviewerMembership = Annotated[Membership, Depends(require_reviewer)]
