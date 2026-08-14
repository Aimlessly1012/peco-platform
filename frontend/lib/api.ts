export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:9200";

/**
 * MCP 端点地址。
 *
 * 子路径部署时 API_BASE 是相对路径（如 `/rag/api`），页面内的 fetch 没问题，
 * 但「claude mcp add」是拿去命令行执行的，必须是带域名的绝对 URL——
 * 所以在浏览器端传入 window.location.origin 补全。SSR 阶段没有 origin，
 * 先渲染相对形式，挂载后再替换，两端首帧一致不触发 hydration 警告。
 */
export function mcpEndpoint(origin?: string): string {
  const base = API_BASE.replace(/\/+$/, "");
  if (/^https?:\/\//i.test(base)) return `${base}/mcp`;
  return `${origin ?? ""}${base}/mcp`;
}

/** 索引深度（M5）：deep 走 LLM 全量理解，fast 只做结构与代码检索。 */
export type IndexDepth = "deep" | "fast";

export interface Project {
  id: string;
  name: string;
  git_url: string;
  default_branch: string | null;
  status: "pending" | "indexing" | "ready" | "failed";
  last_indexed_commit: string | null;
  /** M5 新增：最近一次索引的深度。旧后端不返回该字段。 */
  index_depth?: IndexDepth | null;
  created_at: string;
  updated_at: string;
}

/** 六阶段（M3 新增 report「生成报告」）。 */
export type JobStage =
  | "clone"
  | "parse"
  | "summarize"
  | "embed"
  | "graph"
  | "report";

export interface IndexJob {
  id: string;
  project_id: string;
  kind: string;
  status: "running" | "succeeded" | "failed";
  stage: JobStage;
  progress: number;
  /** 后端统计字典，键随阶段增长（M3 新增 sequences_ok / sequences_fallback）。 */
  stats_json: Record<string, number | string | boolean>;
  error_text: string | null;
  started_at: string;
  finished_at: string | null;
}

/**
 * 业务流程图（M6）：需求视角的流程图，一条业务链路一张。
 * mermaid 为空时用 fallback_text 展示文字版流程。
 */
export interface BusinessFlow {
  title: string;
  mermaid: string;
  fallback_text: string;
}

/** 单个模块的核心流程时序图（后端 sequences_json 元素）。 */
export interface SequenceDiagram {
  module_key: string;
  module_name: string;
  mermaid: string;
  /** mermaid 生成/校验失败时的文字版链路降级内容。 */
  fallback_text: string | null;
}

/**
 * GET /projects/{id}/report —— 理解报告。404 表示尚未生成。
 *
 * M5：mindmap 收窄为 Project→Module 两层（模块子导图由前端按需拼装），
 * 新增模块数据流图与 depth 标记；两个新字段在旧报告上缺省，一律按可选处理。
 */
export interface UnderstandingReport {
  doc_markdown: string;
  mindmap_mermaid: string;
  /**
   * M6 新增：需求功能思维导图的 markdown 层级文本（# 项目 → ## 功能域 → - 功能点），
   * 由 markmap 渲染。旧报告为 null，前端回退渲染 mindmap_mermaid。
   */
  feature_map_markdown?: string | null;
  /**
   * M6 新增：页面结构导图的 markdown 层级文本，同样由 markmap 渲染。
   * 旧报告为 null/缺省，前端隐藏该卡片。
   */
  page_map_markdown?: string | null;
  /** M6 新增：业务流程图列表。旧报告为 null/缺省，前端隐藏该区块。 */
  business_flows?: BusinessFlow[] | null;
  /** M5 新增：模块间数据流 flowchart。旧报告为空/缺省，前端隐藏该卡片。 */
  dataflow_mermaid?: string | null;
  /** M5 新增：产出该报告的索引深度。缺省按 deep 处理。 */
  depth?: IndexDepth | null;
  sequences: SequenceDiagram[];
  generated_at: string;
}

export type ModuleKind = "page" | "api" | "dir" | "shared";

export interface ModuleFile {
  path: string;
  summary: string | null;
}

export interface ModuleInfo {
  name: string;
  kind: ModuleKind;
  route_prefix: string | null;
  summary: string | null;
  files: ModuleFile[];
}

/** GET /projects/{id}/modules —— 功能地图（实时读图库）。 */
export interface ModuleMap {
  modules: ModuleInfo[];
}

export interface ChatSession {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
}

export interface Citation {
  file_path: string;
  start_line: number;
  end_line: number;
  node_id: string;
  symbol: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  citations_json: Citation[];
  created_at: string;
}

/** 带 HTTP 状态码的错误，便于区分 404（如「尚无报告」）与其他失败。 */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isNotFound(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404;
}

/**
 * 401 的统一去向由 AuthProvider 注入。
 *
 * 这里不直接跳 `/login`：子路径部署时裸字符串不带 basePath，必须走 next 的 router。
 * 所以 api 层只负责通知，跳哪、怎么带回跳地址交给上层。
 */
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  unauthorizedHandler = fn;
}

/** /auth/* 自身的 401 是「登录失败」「未登录探测」，不该触发跳转。 */
function isAuthPath(path: string): boolean {
  return path.startsWith("/auth/");
}

function notifyUnauthorized(path: string, status: number): void {
  if (status === 401 && !isAuthPath(path)) unauthorizedHandler?.();
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
    // 登录态是 httpOnly cookie：本地开发跨端口（3200→9200）必须显式带上
    credentials: "include",
  });
  if (!res.ok) {
    notifyUnauthorized(path, res.status);
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail || `请求失败 (${res.status})`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export type UserRole = "admin" | "member";

export interface AuthUser {
  username: string;
  role: UserRole;
}

/** GET /auth/invites 的元素（admin 专用）。 */
export interface InviteCode {
  code: string;
  used_by_name: string | null;
  used_at: string | null;
  created_at: string;
}

export const authApi = {
  me: () => api<AuthUser>("/auth/me"),
  login: (username: string, password: string) =>
    api<AuthUser>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  register: (username: string, password: string, invite_code: string) =>
    api<AuthUser>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password, invite_code }),
    }),
  logout: () => api<void>("/auth/logout", { method: "POST" }),
  listInvites: () => api<InviteCode[]>("/auth/invites"),
  createInvite: () => api<InviteCode>("/auth/invites", { method: "POST" }),
};

export interface AskCallbacks {
  onToken: (t: string) => void;
  onCitations: (c: Citation[]) => void;
  onDone: () => void;
  onError: (message: string) => void;
  /**
   * SSE 注释行（后端约 15s 一个 `: ping`）到达。
   * 首 token 之前唯一能证明「连接还活着」的信号，用来把等待文案说得更笃定。
   */
  onPing?: () => void;
  /**
   * 首 token 之前的处理阶段（M9）：rewrite / classify / rewrite_classify / retrieve / generate。
   * 后端灰度期间可能完全不发，等待文案要能退回纯计时。
   */
  onStage?: (stage: string) => void;
}

/** 解析后端 SSE（event: xxx / data: yyy 块）。 */
export async function askStream(
  sessionId: string,
  question: string,
  cb: AskCallbacks
): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    credentials: "include",
  });
  if (!res.ok || !res.body) {
    notifyUnauthorized(`/sessions/${sessionId}/ask`, res.status);
    const body = await res.json().catch(() => ({}));
    cb.onError(body.detail || `请求失败 (${res.status})`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleBlock = (block: string) => {
    let event = "message";
    let data = "";
    let comment = false;
    for (const line of block.split("\n")) {
      // `:` 开头是 SSE 注释行（心跳）。只跳过这一行，不能丢弃整个块——
      // 心跳可能和真事件粘在同一块里（后端未必在 ping 后补空行）。
      if (line.startsWith(":")) comment = true;
      else if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (comment) cb.onPing?.();
    // 未知 event 一律静默忽略——后端加新事件类型时不能把这一块当错误吞掉
    if (event === "token") cb.onToken(JSON.parse(data).t);
    else if (event === "citations") cb.onCitations(JSON.parse(data));
    else if (event === "stage") cb.onStage?.(JSON.parse(data).stage);
    else if (event === "done") cb.onDone();
    else if (event === "error") cb.onError(JSON.parse(data).message);
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // SSE 规范允许 \r\n 行分隔（sse-starlette 新版默认如此），统一归一为 \n
    // ——否则 indexOf("\n\n") 永远匹配不到块边界，整场流零事件（"一直思考中"事故）
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (block.trim()) handleBlock(block);
    }
  }
  // 流结束后 flush 残余（最后一个块之后可能没有空行）
  buffer += decoder.decode().replace(/\r\n/g, "\n");
  if (buffer.trim()) handleBlock(buffer);
}
