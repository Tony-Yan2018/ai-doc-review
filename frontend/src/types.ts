export type JobStatus = "pending" | "processing" | "completed" | "failed";
export type RiskLevel = "low" | "medium" | "high" | "critical";
export type MembershipRole = "owner" | "admin" | "reviewer" | "viewer";

export interface User {
  id: string;
  email: string;
  full_name: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  role: MembershipRole;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
  tenants: Tenant[];
}

export interface DocumentInfo {
  id: string;
  created_by_user_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface ReviewIssue {
  category: string;
  severity: RiskLevel;
  title: string;
  description: string;
  evidence: string;
  location: string | null;
  recommendation: string;
  suggested_revision: string;
}

export interface ReviewResult {
  overall_risk_level: RiskLevel;
  risk_score: number;
  summary: string;
  issues: ReviewIssue[];
  review_scope: string;
  model_name: string;
  prompt_version: string;
  reviewed_at: string;
}

export interface ReviewJob {
  id: string;
  document_id: string;
  retry_of_job_id: string | null;
  root_job_id: string;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  risk_level: RiskLevel | null;
  result: ReviewResult | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  document: DocumentInfo;
}

export interface JobsPage {
  items: ReviewJob[];
  total: number;
  page: number;
  page_size: number;
}
