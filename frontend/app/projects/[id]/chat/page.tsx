"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
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
  }, [activeSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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

    const patchLast = (patch: Partial<DisplayMessage> | ((m: DisplayMessage) => Partial<DisplayMessage>)) =>
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

  return (
    <div className="flex h-[calc(100vh-8.5rem)] gap-4">
      {/* 会话侧栏 */}
      <aside className="hidden w-56 shrink-0 flex-col rounded-xl border bg-white md:flex">
        <div className="border-b p-3">
          <button
            onClick={newSession}
            className="w-full rounded-lg bg-zinc-900 py-1.5 text-sm text-white hover:bg-zinc-700"
          >
            + 新会话
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => setActiveSession(s.id)}
              className={`mb-1 w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
                s.id === activeSession ? "bg-zinc-100 font-medium" : "hover:bg-zinc-50"
              }`}
            >
              {s.title}
            </button>
          ))}
        </div>
      </aside>

      {/* 主聊天区 */}
      <div className="flex min-w-0 flex-1 flex-col rounded-xl border bg-white">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <a href="/" className="text-sm text-zinc-400 hover:text-zinc-600">← 项目</a>
          <span className="font-medium">{project?.name ?? "…"}</span>
          {project && project.status !== "ready" && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
              项目未就绪（{project.status}），暂不能提问
            </span>
          )}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <div className="pt-16 text-center text-sm text-zinc-400">
              问点什么吧，比如「create_order 函数在哪，是干嘛的？」
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
              <div
                className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm ${
                  m.role === "user" ? "bg-zinc-900 text-white" : "bg-zinc-50 border"
                }`}
              >
                {m.role === "assistant" ? (
                  <div className="prose prose-sm prose-zinc max-w-none [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-zinc-900 [&_pre]:p-3 [&_pre]:text-zinc-100">
                    <ReactMarkdown>{m.content || (m.streaming ? "思考中…" : "")}</ReactMarkdown>
                    {m.citations.length > 0 && <CitationList citations={m.citations} />}
                  </div>
                ) : (
                  <span className="whitespace-pre-wrap">{m.content}</span>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {error && (
          <div className="mx-4 mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="border-t p-3">
          <div className="flex gap-2">
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
              placeholder="询问这个项目的代码…（Enter 发送，Shift+Enter 换行）"
              className="flex-1 resize-none rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-300"
            />
            <button
              onClick={send}
              disabled={busy || project?.status !== "ready"}
              className="self-end rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white hover:bg-zinc-700 disabled:opacity-40"
            >
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CitationList({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 border-t pt-2 not-prose">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-zinc-500 hover:text-zinc-700"
      >
        {open ? "▾" : "▸"} 引用来源（{citations.length}）
      </button>
      {open && (
        <div className="mt-2 space-y-1">
          {citations.map((c, i) => (
            <div key={i} className="rounded-lg bg-white border px-3 py-1.5 text-xs font-mono text-zinc-600">
              {c.file_path}:{c.start_line}-{c.end_line}
              <span className="ml-2 text-zinc-400">{c.symbol}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
