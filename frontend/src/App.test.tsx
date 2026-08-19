import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";


const acme = { id: "tenant-acme", name: "Acme Legal", slug: "acme-legal", role: "owner" };
const northwind = { id: "tenant-northwind", name: "Northwind Policy", slug: "northwind-policy", role: "viewer" };
const reviewerTenant = { ...acme, role: "reviewer" };
const viewerTenant = { ...northwind, role: "viewer" };

const users = {
  owner: { id: "user-owner", email: "owner@acme.local", full_name: "Acme Owner" },
  reviewer: { id: "user-reviewer", email: "reviewer@acme.local", full_name: "Acme Reviewer" },
  viewer: { id: "user-viewer", email: "viewer@northwind.local", full_name: "Northwind Viewer" },
};

const emptyPage = { items: [], total: 0, page: 1, page_size: 50 };

type ApiRequest = {
  url: URL;
  method: string;
  headers: Headers;
  body: BodyInit | null | undefined;
};

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApi(handler: (request: ApiRequest) => Response | Promise<Response>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const source = input instanceof Request ? input : null;
    const request: ApiRequest = {
      url: new URL(source?.url ?? String(input), "http://localhost"),
      method: (init?.method ?? source?.method ?? "GET").toUpperCase(),
      headers: new Headers(init?.headers ?? source?.headers),
      body: init?.body,
    };
    return Promise.resolve(handler(request));
  });
}

function loginResponse(
  user: (typeof users)[keyof typeof users],
  tenants: Array<typeof acme>,
) {
  return {
    access_token: `token-for-${user.id}`,
    token_type: "bearer",
    user,
    tenants,
  };
}

function documentInfo(filename: string) {
  return {
    id: `document-${filename}`,
    filename,
    content_type: "text/plain",
    size_bytes: 128,
    created_at: "2026-08-19T03:00:00Z",
  };
}

function reviewJob(
  id: string,
  filename: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    id,
    document_id: `document-${filename}`,
    status: "completed",
    attempts: 1,
    max_attempts: 3,
    risk_level: "low",
    result: {
      overall_risk_level: "low",
      risk_score: 12,
      summary: "未发现预设高风险表达。",
      issues: [],
      review_scope: "general",
      model_name: "mock-rules-v2",
      prompt_version: "review-v1",
      reviewed_at: "2026-08-19T03:01:00Z",
    },
    error_message: null,
    retry_of_job_id: null,
    root_job_id: id,
    created_at: "2026-08-19T03:00:00Z",
    started_at: "2026-08-19T03:00:10Z",
    completed_at: "2026-08-19T03:01:00Z",
    document: documentInfo(filename),
    ...overrides,
  };
}

function handleAuthRequest(request: ApiRequest, user = users.owner, tenants = [acme, northwind]) {
  if (request.method === "POST" && request.url.pathname.endsWith("/auth/refresh")) {
    return json({ detail: "Authentication required" }, 401);
  }
  if (request.method === "POST" && request.url.pathname.endsWith("/auth/login")) {
    return json(loginResponse(user, tenants));
  }
  if (request.method === "GET" && request.url.pathname.endsWith("/auth/me")) {
    return json(user);
  }
  if (request.method === "GET" && request.url.pathname.endsWith("/tenants")) {
    return json(tenants);
  }
  return null;
}

async function submitLogin(email: string) {
  fireEvent.change(await screen.findByLabelText(/邮箱/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/密码/), { target: { value: "DemoPass123!" } });
  fireEvent.click(screen.getByRole("button", { name: /登录/ }));
}

describe("App", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("shows login and demo account affordances when unauthenticated", async () => {
    mockApi((request) => {
      const auth = handleAuthRequest(request);
      if (auth) return auth;
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    render(<App />);

    expect(await screen.findByRole("heading", { name: /登录|欢迎/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/邮箱/)).toBeInTheDocument();
    expect(screen.getByLabelText(/密码/)).toBeInTheDocument();
    expect(screen.getByText("owner@acme.local")).toBeInTheDocument();
    expect(screen.getByText("reviewer@acme.local")).toBeInTheDocument();
    expect(screen.getByText("viewer@northwind.local")).toBeInTheDocument();
  });

  it("moves from valid login to the workspace with the user and membership role", async () => {
    mockApi((request) => {
      const auth = handleAuthRequest(request);
      if (auth) return auth;
      if (request.url.pathname.endsWith("/review-jobs")) return json(emptyPage);
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    render(<App />);

    await submitLogin("owner@acme.local");

    expect(await screen.findByText("Acme Owner")).toBeInTheDocument();
    expect(screen.getByText(/^(所有者|负责人|owner)$/i)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /当前租户|当前工作区/ })).toHaveValue(acme.id);
  });

  it("switches a multi-tenant user to the selected tenant and loads its history", async () => {
    const historyTenantIds: string[] = [];
    mockApi((request) => {
      const auth = handleAuthRequest(request);
      if (auth) return auth;
      if (request.url.pathname.endsWith("/review-jobs")) {
        const tenantId = request.headers.get("X-Tenant-ID") ?? "";
        historyTenantIds.push(tenantId);
        const item = tenantId === northwind.id
          ? reviewJob("job-northwind", "Northwind-policy.md")
          : reviewJob("job-acme", "Acme-contract.txt");
        return json({ ...emptyPage, items: [item], total: 1 });
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    render(<App />);
    await submitLogin("owner@acme.local");

    expect(await screen.findByText("Acme-contract.txt")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: /当前租户|当前工作区/ }), {
      target: { value: northwind.id },
    });

    expect(await screen.findByText("Northwind-policy.md")).toBeInTheDocument();
    expect(screen.queryByText("Acme-contract.txt")).not.toBeInTheDocument();
    expect(historyTenantIds).toContain(northwind.id);
  });

  it("renders a viewer workspace as read-only without upload or retry controls", async () => {
    const failed = reviewJob("job-failed", "failed-policy.txt", {
      status: "failed",
      risk_level: null,
      result: null,
      error_message: "Mock provider failure",
      completed_at: "2026-08-19T03:01:00Z",
    });
    mockApi((request) => {
      const auth = handleAuthRequest(request, users.viewer, [viewerTenant]);
      if (auth) return auth;
      if (request.url.pathname.endsWith("/review-jobs")) {
        return json({ ...emptyPage, items: [failed], total: 1 });
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    render(<App />);
    await submitLogin("viewer@northwind.local");

    const failedRow = await screen.findByRole("button", { name: /failed-policy\.txt/ });
    fireEvent.click(failedRow);

    expect(screen.getByText(/^(只读成员|阅览成员|viewer)$/i)).toBeInTheDocument();
    expect(screen.queryByText("拖放文档到这里")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重新审核|重试/ })).not.toBeInTheDocument();
  });

  it("allows a reviewer to upload a supported document and selects its new job", async () => {
    const uploaded = reviewJob("job-uploaded-1234", "new-contract.txt", {
      status: "pending",
      risk_level: null,
      result: null,
      started_at: null,
      completed_at: null,
    });
    let receivedUploadTenantId: string | null = null;
    let receivedUploadBody: BodyInit | null | undefined;
    mockApi((request) => {
      const auth = handleAuthRequest(request, users.reviewer, [reviewerTenant]);
      if (auth) return auth;
      if (request.method === "GET" && request.url.pathname.endsWith("/review-jobs")) return json(emptyPage);
      if (request.method === "POST" && request.url.pathname.endsWith("/documents")) {
        receivedUploadTenantId = request.headers.get("X-Tenant-ID");
        receivedUploadBody = request.body;
        return json({ document: uploaded.document, review_job: uploaded }, 201);
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    const { container } = render(<App />);
    await submitLogin("reviewer@acme.local");
    await screen.findByText("还没有审核记录");

    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    const file = new File(["Unlimited liability"], "new-contract.txt", { type: "text/plain" });
    fireEvent.change(input!, { target: { files: [file] } });

    expect(await screen.findByText(/任务 job-uplo/)).toBeInTheDocument();
    expect(receivedUploadTenantId).toBe(acme.id);
    expect(receivedUploadBody).toBeInstanceOf(FormData);
  });

  it("keeps a failed attempt and selects the new job returned by retry", async () => {
    const failed = reviewJob("old-job-123456", "broken.txt", {
      status: "failed",
      risk_level: null,
      result: null,
      error_message: "Mock provider failure",
    });
    const retried = reviewJob("new-job-987654", "broken.txt", {
      status: "pending",
      attempts: 0,
      risk_level: null,
      result: null,
      error_message: null,
      retry_of_job_id: failed.id,
      root_job_id: failed.id,
      started_at: null,
      completed_at: null,
    });
    mockApi((request) => {
      const auth = handleAuthRequest(request, users.reviewer, [reviewerTenant]);
      if (auth) return auth;
      if (request.method === "GET" && request.url.pathname.endsWith("/review-jobs")) {
        return json({ ...emptyPage, items: [failed], total: 1 });
      }
      if (request.method === "POST" && request.url.pathname.endsWith(`/review-jobs/${failed.id}/retry`)) {
        return json(retried, 201);
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    render(<App />);
    await submitLogin("reviewer@acme.local");

    fireEvent.click(await screen.findByRole("button", { name: /broken\.txt/ }));
    fireEvent.click(screen.getByRole("button", { name: /重新审核|重试/ }));

    expect(await screen.findByText(/任务 new-job-/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /broken\.txt/ })).toHaveLength(2);
  });

  it("renders risk score and actionable issue details in a completed report", async () => {
    const completed = reviewJob("job-report-1234", "supplier-contract.txt", {
      risk_level: "high",
      result: {
        overall_risk_level: "high",
        risk_score: 86,
        summary: "存在显著责任风险。",
        review_scope: "contract",
        model_name: "mock-rules-v2",
        prompt_version: "review-v1",
        reviewed_at: "2026-08-19T03:01:00Z",
        issues: [
          {
            category: "liability",
            severity: "high",
            title: "存在无限责任条款",
            description: "责任范围没有明确上限。",
            evidence: "Supplier accepts unlimited liability.",
            location: "第 4 段",
            recommendation: "设置明确的责任上限。",
            suggested_revision: "责任总额不超过过去十二个月已支付费用。",
          },
        ],
      },
    });
    mockApi((request) => {
      const auth = handleAuthRequest(request, users.reviewer, [reviewerTenant]);
      if (auth) return auth;
      if (request.url.pathname.endsWith("/review-jobs")) {
        return json({ ...emptyPage, items: [completed], total: 1 });
      }
      throw new Error(`Unexpected request: ${request.method} ${request.url}`);
    });
    render(<App />);
    await submitLogin("reviewer@acme.local");

    fireEvent.click(await screen.findByRole("button", { name: /supplier-contract\.txt/ }));

    expect(screen.getAllByText("高风险").length).toBeGreaterThan(0);
    expect(screen.getByText("86")).toBeInTheDocument();
    expect(screen.getByText("Supplier accepts unlimited liability.")).toBeInTheDocument();
    expect(screen.getByText("第 4 段")).toBeInTheDocument();
    expect(screen.getByText("设置明确的责任上限。")).toBeInTheDocument();
    expect(screen.getByText("责任总额不超过过去十二个月已支付费用。")).toBeInTheDocument();
  });
});
