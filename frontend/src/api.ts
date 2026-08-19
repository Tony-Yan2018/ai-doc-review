import type { AuthResponse, JobsPage, ReviewJob, Tenant } from "./types";

const API_URL = "/api/v1";
let accessToken: string | null = null;
let refreshRequest: Promise<AuthResponse> | null = null;

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export function clearAccessToken() {
  accessToken = null;
}

function rememberAuth(auth: AuthResponse) {
  accessToken = auth.access_token;
  return auth;
}

async function parseError(response: Response): Promise<ApiError> {
  const payload = await response.json().catch(() => null) as { detail?: string } | null;
  const fallback: Record<number, string> = {
    401: "登录已过期，请重新登录",
    403: "当前角色没有执行此操作的权限",
    404: "请求的资源不存在或你无权访问",
  };
  return new ApiError(payload?.detail ?? fallback[response.status] ?? `请求失败 (${response.status})`, response.status);
}

async function rawRequest(path: string, tenantId?: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (tenantId) headers.set("X-Tenant-ID", tenantId);
  try {
    return await fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
  } catch {
    throw new ApiError("网络连接失败，请检查服务是否正在运行", 0);
  }
}

async function refreshSession(): Promise<AuthResponse> {
  if (!refreshRequest) {
    refreshRequest = rawRequest("/auth/refresh", undefined, { method: "POST" })
      .then(async (response) => {
        if (!response.ok) throw await parseError(response);
        return rememberAuth(await response.json() as AuthResponse);
      })
      .finally(() => { refreshRequest = null; });
  }
  return refreshRequest;
}

async function request<T>(path: string, tenantId?: string, init?: RequestInit, retry = true): Promise<T> {
  let response = await rawRequest(path, tenantId, init);
  if (response.status === 401 && retry && path !== "/auth/refresh" && path !== "/auth/login") {
    await refreshSession();
    response = await rawRequest(path, tenantId, init);
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", undefined, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }, false).then(rememberAuth),
  refresh: () => refreshSession(),
  logout: async () => {
    try {
      await request<void>("/auth/logout", undefined, { method: "POST" }, false);
    } finally {
      clearAccessToken();
    }
  },
  listTenants: () => request<Tenant[]>("/tenants"),
  listJobs: (tenantId: string) => request<JobsPage>("/review-jobs?page_size=50", tenantId),
  getJob: (tenantId: string, jobId: string) => request<ReviewJob>(`/review-jobs/${jobId}`, tenantId),
  retryJob: (tenantId: string, jobId: string) =>
    request<ReviewJob>(`/review-jobs/${jobId}/retry`, tenantId, { method: "POST" }),
  upload: async (tenantId: string, file: File): Promise<ReviewJob> => {
    const body = new FormData();
    body.append("file", file);
    const payload = await request<{ review_job: ReviewJob }>("/documents", tenantId, { method: "POST", body });
    return payload.review_job;
  },
  download: async (tenantId: string, documentId: string): Promise<Blob> => {
    let response = await rawRequest(`/documents/${documentId}/download`, tenantId);
    if (response.status === 401) {
      await refreshSession();
      response = await rawRequest(`/documents/${documentId}/download`, tenantId);
    }
    if (!response.ok) throw await parseError(response);
    return response.blob();
  },
};
