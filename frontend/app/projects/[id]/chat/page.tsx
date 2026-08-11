"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  api,
  askStream,
  ChatMessage,
  ChatSession,
  Citation,
  Project,
} from "@/lib/api";

interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  streaming?: boolean;
}

export default function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<Project>(`/projects/${projectId}`).then(setProject).catch(() => {});
    api<ChatSession[]>(`/projects/${projectId}/sessions`).then((list) => {
      setSessions(list);
      if (list.length > 0) setActiveSession(list[0].id);
    });
  }, [projectId]);

  useEffect(() => {
    if (!activeSession) {
      setMessages([]);
      return;
    }
    api<ChatMessage[]>(`/sessions/${activeSession}/messages`).then((list) =>
      setMessages(
        list.map((m) => ({
          role: m.role,
          content: m.content,
          citations: m.citations_json || [],
        }))
      )
    );
    setSelected(null);
  }, [activeSession]);

  useEffect(() => {
    const el = bottomRef.current?.parentElement;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const newSession = useCallback(async () => {
    const s = await api<ChatSession>(`/projects/${projectId}/sessions`, {
      method: "POST",
      body: JSON.stringify({ title: `会话 ${sessions.length + 1}` }),
    });
    setSessions((prev) => [s, ...prev]);
    setActiveSession(s.id);
  }, [projectId, sessions.length]);

  const send = async () => {
    if (!input.trim() || busy) return;
    let sessionId = activeSession;
    if (!sessionId) {
      const s = await api<ChatSession>(`/projects/${projectId}/sessions`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setSessions((prev) => [s, ...prev]);
      setActiveSession(s.id);
      sessionId = s.id;
    }
    const question = input.trim();
    setInput("");
    setError("");
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question, citations: [] },
      { role: "assistant", content: "", citations: [], streaming: true },
    ]);
    setSelected(null);

    const patchLast = (
      patch: Partial<DisplayMessage> | ((m: DisplayMessage) => Partial<DisplayMessage>)
    ) =>
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        const p = typeof patch === "function" ? patch(last) : patch;
        next[next.length - 1] = { ...last, ...p };
        return next;
      });

    await askStream(sessionId, question, {
      onToken: (t) => patchLast((m) => ({ content: m.content + t })),
      onCitations: (c) => patchLast({ citations: c }),
      onDone: () => {
        patchLast({ streaming: false });
        setBusy(false);
      },
      onError: (message) => {
        setError(message);
        patchLast({ streaming: false });
        setBusy(false);
      },
    });
  };

  /** 右栏显示：选中的回答，否则最后一条带引用的回答 */
  const sourceIndex = useMemo(() => {
    if (selected !== null && messages[selected]?.role === "assistant") return selected;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant" && messages[i].citations.length > 0) return i;
    }
    return null;
  }, [selected, messages]);
  const citations = sourceIndex !== null ? messages[sourceIndex].citations : [];

  return (
    <div className="flex min-h-0 flex-1">
      {/* 会话侧栏 */}
      <aside className="hidden w-[212px] flex-none flex-col gap-4 border-r border-line bg-canvas px-4 py-[18px] md:flex">
        <button
          onClick={newSession}
          className="border border-accent bg-accent/[.06] py-2 text-[11px] font-medium tracking-wide text-accent hover:bg-accent/[.12]"
        >
          + 新会话
        </button>
        <div className="text-[10px] tracking-label text-dim">SESSIONS</div>
        <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => setActiveSession(s.id)}
              className={`truncate px-3 py-2 text-left text-xs ${
                s.id === activeSession
                  ? "border-l-2 border-accent bg-panel pl-2.5"
                  : "text-muted hover:text-ink"
              }`}
            >
              {s.title}
            </button>
          ))}
        </div>
        <div className="text-[10px] leading-relaxed text-faint">
          RETRIEVAL
          <br />
          <span className="text-muted">vector + graph · top_k 8</span>
        </div>
      </aside>

      {/* 答案栏 */}
      <div className="flex min-w-0 flex-1 flex-col border-r border-line">
        <div className="flex flex-none items-center gap-2.5 border-b border-line bg-panel px-[30px] py-3">
          <a href="/" className="text-xs text-faint hover:text-ink">
            ← 项目
          </a>
          <a
            href={`/projects/${projectId}`}
            className="text-[13px] font-medium hover:text-accent"
          >
            {project?.name ?? "…"}
          </a>
          <a
            href={`/projects/${projectId}`}
            className="text-[10px] tracking-wide text-faint hover:text-accent"
          >
            详情 →
          </a>
          {project && project.status !== "ready" && (
            <span className="border border-danger/40 px-2 py-[2px] text-[10px] tracking-wide text-danger">
              {project.status.toUpperCase()} · 暂不能提问
            </span>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-[30px] py-[26px]">
          {messages.length === 0 && (
            <div className="pt-16 text-center text-xs text-faint">
              问点什么吧，比如「create_order 函数在哪，是干嘛的？」
            </div>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[76%] whitespace-pre-wrap bg-ink px-3.5 py-2.5 text-[13px] leading-relaxed text-paper">
                  {m.content}
                </div>
              </div>
            ) : (
              <div key={i} className="flex flex-col gap-3">
                <div className="flex items-center gap-2.5">
                  <span className="block h-4 w-4 bg-accent" />
                  <span className="text-[10px] tracking-label text-dim">
                    ANSWER
                    {m.citations.length > 0 ? ` · 命中 ${m.citations.length} 个代码块` : ""}
                  </span>
                </div>
                <div
                  onClick={() => setSelected(i)}
                  className={`cursor-default border bg-panel px-5 py-[18px] text-[13px] leading-[1.95] ${
                    sourceIndex === i ? "border-line" : "border-hair"
                  }`}
                >
                  <div className="prose prose-sm max-w-none prose-p:my-0 prose-p:mb-3 prose-p:last:mb-0 prose-code:bg-accent/[.08] prose-code:px-1 prose-code:py-px prose-code:text-accent prose-code:before:content-none prose-code:after:content-none prose-pre:overflow-x-auto prose-pre:rounded-none prose-pre:border prose-pre:border-line prose-pre:bg-shade prose-pre:text-ink2">
                    <ReactMarkdown>{m.content || (m.streaming ? "思考中…" : "")}</ReactMarkdown>
                  </div>
                </div>
              </div>
            )
          )}
          <div ref={bottomRef} />
        </div>

        {error && (
          <div className="mx-[30px] mb-2 border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}

        <div className="flex-none border-t border-line px-[30px] pb-5 pt-4">
          <div className="flex flex-col gap-3 border border-line bg-panel px-3.5 py-3">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={2}
              placeholder="询问这个项目的代码…"
              className="w-full resize-none border-0 bg-transparent p-0 text-[13px] placeholder:text-faint focus:outline-none"
            />
            <div className="flex items-center gap-2.5">
              <span className="text-[10px] tracking-wide text-faint">
                ENTER 发送 · SHIFT+ENTER 换行
              </span>
              <button
                onClick={send}
                disabled={busy || project?.status !== "ready"}
                className="ml-auto bg-ink px-4 py-[7px] text-[11px] font-medium tracking-wide text-paper disabled:opacity-40"
              >
                发送
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 源码栏 */}
      <aside className="hidden w-[472px] flex-none flex-col bg-canvas lg:flex">
        <div className="flex flex-none items-center gap-2.5 border-b border-line px-[18px] py-3.5">
          <span className="text-[10px] tracking-label text-dim">SOURCES · {citations.length}</span>
          <span className="ml-auto text-[10px] tracking-wide text-faint">SORT BY SCORE</span>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3.5">
          {citations.length === 0 && (
            <div className="pt-12 text-center text-[11px] text-faint">
              回答产生的引用会出现在这里
            </div>
          )}
          {citations.map((c, i) => (
            <div
              key={`${c.node_id}-${i}`}
              className={`bg-panel ${i === 0 ? "border border-accent/40" : "border border-line"}`}
            >
              <div className="flex items-center gap-2.5 border-b border-hair px-3 py-2.5">
                <span
                  className={`flex h-4 w-4 items-center justify-center text-[10px] ${
                    i === 0 ? "bg-accent text-paper" : "bg-hair text-ink2"
                  }`}
                >
                  {i + 1}
                </span>
                <span className="truncate text-[11.5px]">
                  {c.file_path}
                  <span className="text-dim">
                    :{c.start_line}-{c.end_line}
                  </span>
                </span>
              </div>
              <div className="flex gap-2 px-3 py-2 text-[10px] tracking-wide text-dim">
                <span className="truncate">{c.symbol || "—"}</span>
                {/* 设计稿这里链到 /map?node=…，该路由 M3 未实现；改指详情页「功能地图」页签 */}
                <a
                  href={`/projects/${projectId}?tab=modules`}
                  className="ml-auto whitespace-nowrap text-accent hover:underline"
                >
                  功能地图 →
                </a>
              </div>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
