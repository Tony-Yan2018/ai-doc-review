import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, clearAccessToken } from "./api";
import type { AuthResponse, JobStatus, MembershipRole, ReviewIssue, ReviewJob, RiskLevel } from "./types";

const DEMO_PASSWORD = "DemoPass123!";
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];

const statusLabel: Record<JobStatus, string> = {
  pending: "等待中",
  processing: "审核中",
  completed: "已完成",
  failed: "失败",
};
const riskLabel: Record<RiskLevel, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  critical: "严重风险",
};
const roleLabel: Record<MembershipRole, string> = {
  owner: "所有者",
  admin: "管理员",
  reviewer: "审核员",
  viewer: "只读成员",
};
const compactRiskLabel: Record<RiskLevel, string> = { low: "低", medium: "中", high: "高", critical: "严重" };

function BrandMark() {
  return <div className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M9 4h10l5 5v18H9z" /><path d="M19 4v6h6M13 15h7M13 20h7" /></svg></div>;
}

function UploadIcon() {
  return <svg className="upload-icon" viewBox="0 0 48 48" aria-hidden="true"><path d="M24 31V13m0 0-7 7m7-7 7 7"/><path d="M10 31v5a3 3 0 0 0 3 3h22a3 3 0 0 0 3-3v-5"/></svg>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatBytes(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function StatusPill({ job }: { job: ReviewJob }) {
  const label = job.status === "completed" && job.risk_level ? compactRiskLabel[job.risk_level] : statusLabel[job.status];
  const variant = job.status === "completed" && job.risk_level ? job.risk_level : job.status;
  return <span className={`pill pill-${variant}`}><i />{label}</span>;
}

function EmptyResult() {
  return <div className="empty-result"><div className="radar"><span /><span /><span /><i /></div><h3>选择一条审核记录</h3><p>结构化风险结果、证据和修改建议会显示在这里。</p></div>;
}

function IssueCard({ issue, index }: { issue: ReviewIssue; index: number }) {
  return (
    <article className={`issue issue-${issue.severity}`}>
      <div className="issue-top">
        <span className="issue-index">{String(index + 1).padStart(2, "0")}</span>
        <div><span className="issue-category">{issue.category}</span><h4>{issue.title}</h4></div>
        <span className={`severity severity-${issue.severity}`}>{compactRiskLabel[issue.severity]}</span>
      </div>
      <p className="issue-description">{issue.description}</p>
      <blockquote><span>原文证据</span>{issue.location && <b>{issue.location}</b>}{issue.evidence}</blockquote>
      <div className="issue-actions"><div><strong>审核建议</strong><p>{issue.recommendation}</p></div><div><strong>建议改写</strong><p>{issue.suggested_revision}</p></div></div>
    </article>
  );
}

function LoginScreen({ onAuthenticated, initialError }: { onAuthenticated: (auth: AuthResponse) => void; initialError?: string | null }) {
  const [email, setEmail] = useState("owner@acme.local");
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(initialError ?? null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      onAuthenticated(await api.login(email, password));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  function fill(emailAddress: string) {
    setEmail(emailAddress);
    setPassword(DEMO_PASSWORD);
    setError(null);
  }

  return (
    <div className="login-page">
      <section className="login-story">
        <div className="brand login-brand"><BrandMark /><div><strong>ClausePilot</strong><span>AI DOCUMENT REVIEW</span></div></div>
        <div><span className="eyebrow">SECURE REVIEW WORKSPACE</span><h1>把复杂条款，<em>变成清晰决策。</em></h1><p>面向团队的多租户 AI 文档审核平台。风险、证据与修改建议，一处完成。</p></div>
        <small>DETERMINISTIC MOCK ENGINE · LOCAL PRODUCT MVP</small>
      </section>
      <section className="login-panel">
        <form onSubmit={submit}>
          <span className="eyebrow">MEMBER SIGN IN</span><h2>登录工作区</h2><p>使用本地演示账号进入所属租户。</p>
          {error && <div className="login-error" role="alert">{error}</div>}
          <label><span>邮箱</span><input aria-label="邮箱" type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required /></label>
          <label><span>密码</span><input aria-label="密码" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
          <button className="primary-action" type="submit" disabled={submitting}>{submitting ? "正在验证…" : "登录"}</button>
          <div className="demo-accounts"><span>快速填充演示账号</span><button type="button" onClick={() => fill("owner@acme.local")}>owner@acme.local</button><button type="button" onClick={() => fill("reviewer@acme.local")}>reviewer@acme.local</button><button type="button" onClick={() => fill("viewer@northwind.local")}>viewer@northwind.local</button></div>
          <small>所有账号密码：{DEMO_PASSWORD}</small>
        </form>
      </section>
    </div>
  );
}

export default function App() {
  const [auth, setAuth] = useState<AuthResponse | null>(null);
  const [booting, setBooting] = useState(true);
  const [tenantId, setTenantId] = useState("");
  const [jobs, setJobs] = useState<ReviewJob[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all");
  const [riskFilter, setRiskFilter] = useState<RiskLevel | "all">("all");
  const fileInput = useRef<HTMLInputElement>(null);

  const tenant = auth?.tenants.find((item) => item.id === tenantId) ?? null;
  const canReview = Boolean(tenant && tenant.role !== "viewer");
  const selected = useMemo(() => jobs.find((job) => job.id === selectedId) ?? null, [jobs, selectedId]);
  const activeCount = jobs.filter((job) => job.status === "pending" || job.status === "processing").length;
  const filteredJobs = useMemo(() => jobs.filter((job) =>
    (statusFilter === "all" || job.status === statusFilter) &&
    (riskFilter === "all" || job.risk_level === riskFilter)
  ), [jobs, riskFilter, statusFilter]);

  function acceptAuth(nextAuth: AuthResponse) {
    setAuth(nextAuth);
    setTenantId((current) => nextAuth.tenants.some((item) => item.id === current) ? current : nextAuth.tenants[0]?.id ?? "");
    setError(null);
  }

  const handleError = useCallback((err: unknown, fallback: string) => {
    if (err instanceof ApiError && err.status === 401) {
      clearAccessToken();
      setAuth(null);
      setTenantId("");
      setJobs([]);
      setSelectedId(null);
    }
    setError(err instanceof Error ? err.message : fallback);
  }, []);

  useEffect(() => {
    api.refresh().then(acceptAuth).catch((err) => {
      if (!(err instanceof ApiError) || err.status !== 401) setError(err instanceof Error ? err.message : "无法恢复登录状态");
    }).finally(() => setBooting(false));
  }, []);

  const loadJobs = useCallback(async (currentTenant: string, quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const page = await api.listJobs(currentTenant);
      setJobs(page.items);
      setError(null);
    } catch (err) {
      handleError(err, "加载审核记录失败");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [handleError]);

  useEffect(() => {
    if (!auth || !tenantId) return;
    setSelectedId(null);
    setJobs([]);
    void loadJobs(tenantId);
  }, [auth, tenantId, loadJobs]);

  useEffect(() => {
    if (!auth || !tenantId || activeCount === 0) return;
    const timer = window.setInterval(() => void loadJobs(tenantId, true), 1800);
    return () => window.clearInterval(timer);
  }, [auth, tenantId, activeCount, loadJobs]);

  async function upload(file?: File) {
    if (!file || !tenantId || !canReview) return;
    const extension = ALLOWED_EXTENSIONS.find((item) => file.name.toLowerCase().endsWith(item));
    if (!extension) { setError("仅支持 PDF、DOCX、TXT 和 MD 文件"); return; }
    if (file.size > MAX_FILE_BYTES) { setError("文件不能超过 20 MB"); return; }
    setUploading(true);
    try {
      const job = await api.upload(tenantId, file);
      setJobs((current) => [job, ...current]);
      setSelectedId(job.id);
      setError(null);
    } catch (err) {
      handleError(err, "上传失败");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function retry() {
    if (!tenantId || !selected || !canReview) return;
    try {
      const retried = await api.retryJob(tenantId, selected.id);
      setJobs((current) => [retried, ...current]);
      setSelectedId(retried.id);
      setError(null);
    } catch (err) {
      handleError(err, "重试失败");
    }
  }

  async function download() {
    if (!tenantId || !selected) return;
    try {
      const blob = await api.download(tenantId, selected.document_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = selected.document.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      handleError(err, "下载失败");
    }
  }

  async function logout() {
    try { await api.logout(); } catch { /* Local logout still clears the in-memory token. */ }
    setAuth(null);
    setTenantId("");
    setJobs([]);
    setSelectedId(null);
    setError(null);
  }

  if (booting) return <div className="boot-screen"><BrandMark /><span>正在恢复安全会话…</span></div>;
  if (!auth) return <LoginScreen onAuthenticated={acceptAuth} initialError={error} />;

  return (
    <div className="app-shell">
      <header>
        <div className="brand"><BrandMark /><div><strong>ClausePilot</strong><span>AI DOCUMENT REVIEW</span></div></div>
        <div className="header-actions">
          <span className="environment"><i /> MOCK ENGINE</span>
          <label className="tenant-select"><span>当前工作区</span><select aria-label="当前租户" value={tenantId} onChange={(event) => setTenantId(event.target.value)}>{auth.tenants.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <div className="member-summary"><div className="avatar">{auth.user.full_name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</div><div><strong>{auth.user.full_name}</strong><span>{tenant ? roleLabel[tenant.role] : ""}</span></div></div>
          <button className="logout-button" onClick={() => void logout()}>退出</button>
        </div>
      </header>

      <main>
        <section className="intro"><div><span className="eyebrow">REVIEW WORKSPACE</span><h1>文档审核，<em>风险先见。</em></h1><p>{tenant?.name} · 上传业务文档，获得结构化风险判断与可执行建议。</p></div><div className="metrics"><div><strong>{jobs.length}</strong><span>审核总数</span></div><div><strong>{activeCount}</strong><span>进行中</span></div><div><strong>{jobs.filter((job) => job.status === "failed").length}</strong><span>失败任务</span></div><div><strong>{jobs.filter((job) => job.risk_level === "high" || job.risk_level === "critical").length}</strong><span>重点风险</span></div></div></section>

        {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label="关闭错误" onClick={() => setError(null)}>×</button></div>}

        <section className="workspace-grid">
          <aside className="left-column">
            {canReview ? <div className={`dropzone ${dragging ? "dragging" : ""} ${uploading ? "uploading" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files[0]); }} onClick={() => !uploading && fileInput.current?.click()} role="button" tabIndex={0} onKeyDown={(event) => event.key === "Enter" && fileInput.current?.click()}>
              <input ref={fileInput} aria-label="选择文档" type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => void upload(event.target.files?.[0])} hidden /><UploadIcon /><strong>{uploading ? "正在安全上传…" : "拖放文档到这里"}</strong><span>或点击选择文件</span><small>PDF · DOCX · TXT · MD　最大 20 MB</small>
            </div> : <div className="read-only-card"><span>RESTRICTED ACCESS</span><strong>当前工作区仅可查看</strong><p>你可以查看历史审核并下载原始文档，但不能上传或重试任务。</p></div>}

            <div className="history-panel">
              <div className="section-title"><div><span>REVIEW HISTORY</span><h2>审核记录</h2></div><button aria-label="刷新" onClick={() => tenantId && void loadJobs(tenantId)}>↻</button></div>
              <div className="filters"><label>状态<select aria-label="状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as JobStatus | "all")}><option value="all">全部</option><option value="pending">等待中</option><option value="processing">审核中</option><option value="completed">已完成</option><option value="failed">失败</option></select></label><label>风险<select aria-label="风险筛选" value={riskFilter} onChange={(event) => setRiskFilter(event.target.value as RiskLevel | "all")}><option value="all">全部</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">严重</option></select></label></div>
              <div className="job-list">{loading ? <div className="list-state">正在加载记录…</div> : filteredJobs.length === 0 ? <div className="list-state">{jobs.length ? "没有符合筛选条件的记录" : "还没有审核记录"}</div> : filteredJobs.map((job) => <button key={job.id} className={`job-row ${selectedId === job.id ? "selected" : ""}`} onClick={() => setSelectedId(job.id)}><div className="file-tile">{job.document.filename.split(".").pop()?.toUpperCase()}</div><div className="job-copy"><strong title={job.document.filename}>{job.document.filename}</strong><span>{formatDate(job.created_at)} · {formatBytes(job.document.size_bytes)}</span></div><StatusPill job={job} /></button>)}</div>
            </div>
          </aside>

          <section className="result-panel">
            {!selected ? <EmptyResult /> : <><div className="result-header"><div><span className="eyebrow">REVIEW REPORT</span><h2>文档 · {selected.document.filename}</h2><p>任务 {selected.id.slice(0, 8)}{selected.retry_of_job_id ? " · 重试任务" : ""} · 执行 {selected.attempts} 次</p></div><div className="result-actions"><button onClick={() => void download()}>下载原文</button><StatusPill job={selected} /></div></div>
              {(selected.status === "pending" || selected.status === "processing") && <div className="processing-state"><div className="scanner"><span /></div><h3>{selected.status === "pending" ? "任务等待 Worker 接收" : "正在识别条款与潜在风险"}</h3><p>完成后报告会自动更新，无需刷新页面。</p></div>}
              {selected.status === "failed" && <div className="failed-state"><span>!</span><h3>本次审核没有完成</h3><p>{selected.error_message}</p>{canReview && <button onClick={() => void retry()}>创建重试任务</button>}</div>}
              {selected.status === "completed" && selected.result && <div className="report"><div className={`risk-summary risk-${selected.result.overall_risk_level}`}><div className="risk-score"><span>OVERALL RISK</span><strong>{riskLabel[selected.result.overall_risk_level]}</strong><b>{selected.result.risk_score}<small>/100</small></b></div><p>{selected.result.summary}</p><div className="issue-count"><strong>{selected.result.issues.length}</strong><span>关注项</span></div></div><div className="report-meta"><span>范围 {selected.result.review_scope}</span><span>模型 {selected.result.model_name}</span><span>提示词 {selected.result.prompt_version}</span><span>{formatDate(selected.result.reviewed_at)}</span></div><div className="report-section"><div className="section-title"><div><span>FINDINGS</span><h3>风险与问题</h3></div></div>{selected.result.issues.length ? selected.result.issues.map((issue, index) => <IssueCard key={`${issue.category}-${index}`} issue={issue} index={index} />) : <div className="clean-state">未命中预设风险规则，仍建议进行人工复核。</div>}</div></div>}
            </>}
          </section>
        </section>
      </main>
    </div>
  );
}
