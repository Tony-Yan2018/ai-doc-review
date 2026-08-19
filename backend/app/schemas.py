from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import JobStatus, MembershipRole


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    slug: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str


class TenantMembershipOut(TenantOut):
    role: MembershipRole


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthContextOut(BaseModel):
    user: UserOut
    tenants: list[TenantMembershipOut]


class LoginResponse(AuthContextOut):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_by_user_id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class ReviewIssue(BaseModel):
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    title: str
    description: str
    evidence: str
    location: str | None
    recommendation: str
    suggested_revision: str


class ReviewResult(BaseModel):
    overall_risk_level: Literal["low", "medium", "high", "critical"]
    risk_score: int = Field(ge=0, le=100)
    summary: str
    issues: list[ReviewIssue]
    review_scope: str
    model_name: str
    prompt_version: str
    reviewed_at: datetime


class ReviewJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    document_id: str
    retry_of_job_id: str | None
    root_job_id: str
    status: JobStatus
    attempts: int
    max_attempts: int
    risk_level: str | None
    result: ReviewResult | None
    error_message: str | None
    available_at: datetime
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    document: DocumentOut


class UploadResponse(BaseModel):
    document: DocumentOut
    review_job: ReviewJobOut


class PaginatedJobs(BaseModel):
    items: list[ReviewJobOut]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
