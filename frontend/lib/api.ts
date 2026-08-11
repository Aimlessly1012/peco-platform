export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

export interface Project {
  id: string;
  name: string;
  git_url: string;
  default_branch: string | null;
  status: "pending" | "indexing" | "ready" | "failed";
  last_indexed_commit: string | null;
  created_at: string;
  updated_at: string;
}

export interface IndexJob {
  id: string;
  project_id: string;
  kind: string;
  status: "running" | "succeeded" | "failed";
  stage: "clone" | "parse" | "summarize" | "embed" | "graph";
  progress: number;
  stats_json: Record<string, number>;
  error_text: string | null;
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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败 (${res.status})`);
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
