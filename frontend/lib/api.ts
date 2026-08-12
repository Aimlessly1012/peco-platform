export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail || `请求失败 (${res.status})`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface AskCallbacks {
  onToken: (t: string) => void;
  onCitations: (c: Citation[]) => void;
  onDone: () => void;
  onError: (message: string) => void;
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
  });
  if (!res.ok || !res.body) {
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
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (event === "token") cb.onToken(JSON.parse(data).t);
    else if (event === "citations") cb.onCitations(JSON.parse(data));
    else if (event === "done") cb.onDone();
    else if (event === "error") cb.onError(JSON.parse(data).message);
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (block.trim()) handleBlock(block);
    }
  }
}
