import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class MembershipRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    reviewer = "reviewer"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[MembershipRole] = mapped_column(Enum(MembershipRole, native_enum=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship()


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    tenant: Mapped[Tenant] = relationship()
    created_by: Mapped[User] = relationship()


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    review_job_id: Mapped[str] = mapped_column(ForeignKey("review_jobs.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ReviewJob(Base):
    __tablename__ = "review_jobs"
    __table_args__ = (
        UniqueConstraint("retry_of_job_id", name="uq_review_jobs_retry_of_job_id"),
        Index("ix_review_jobs_tenant_created", "tenant_id", "created_at"),
        Index("ix_review_jobs_claim", "status", "available_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    retry_of_job_id: Mapped[str | None] = mapped_column(ForeignKey("review_jobs.id", ondelete="SET NULL"))
    root_job_id: Mapped[str] = mapped_column(ForeignKey("review_jobs.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False), default=JobStatus.pending, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    result: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship()
