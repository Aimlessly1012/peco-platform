"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import PathText, {
  basename,
  dirname,
  looksLikePath,
  middleEllipsis,
} from "@/components/rag/PathText";
import {
  api,
  askStream,
  ChatMessage,
  ChatSession,
  Citation,
  Project,
} from "@/lib/rag/api";
import ThinkingIndicator from "@/components/rag/ThinkingIndicator";
import { rehypeCitationRefs } from "@/lib/rag/citations";

interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  streaming?: boolean;
  /** 发起时刻，等待态用它计时（仅本次会话内有效，不落库）。 */
  startedAt?: number;
  /** 收到过 SSE 心跳 = 连接确实活着。 */
  pinged?: boolean;
  /** 后端上报的处理阶段（M9），等待文案优先用它。 */
  stage?: string;
  /** 出错的回答保留在原位，可就地重试。 */
  failed?: string;
}

/** 答案正文：引用上标可点，长路径 inline code 中段省略。 */
function AnswerBody({
  content,
  onCite,
}: {
  content: string;
  onCite: (n: number) => void;
}) {
  const components = useMemo<Components>(
    () => ({
      sup({ node, className, children, ...rest }) {
        void node;
        if (!String(className ?? "").includes("cite-ref")) {
          return (
            <sup className={className} {...rest}>
              {children}
            </sup>
          );
        }
        const n = Number.parseInt(String(children), 10);
        return (
          <button
            type="button"
            title={`跳转到右侧第 ${n} 条引用`}
            onClick={(e) => {
              e.stopPropagation();
              if (Number.isFinite(n)) onCite(n);
            }}
            className="mx-[1px] align-super text-[10px] font-medium text-accent hover:underline"
          >
            [{n}]
          </button>
        );
      },
      code({ node, className, children, ...rest }) {
        void node;
        const text = String(children ?? "");
        // v9 没有 inline 标记：块级代码带 language-* 或含换行，据此区分
        const isInline = !className && !text.includes("\n");
        if (isInline && looksLikePath(text)) {
          return (
            <code className="bg-accent/[.08] px-1 py-px text-accent">
              <PathText value={text} />
            </code>
          );
        }
        return (
          <code className={className} {...rest}>
            {children}
          </code>
        );
      },
    }),
    [onCite]
  );

  return (
    <ReactMarkdown rehypePlugins={[rehypeCitationRefs]} components={components}>
      {content}
    </ReactMarkdown>
  );
}

/** symbol 常带个括号后缀（`create_order (function)`），拆出来做徽章；拆不动就原样显示。 */
function splitSymbol(symbol: string): { name: string; kind: string | null } {
  const s = (symbol || "").trim();
  const m = s.match(/^(.*\S)\s*[（([]([^）)\]]{1,16})[）)\]]$/);
  return m ? { name: m[1], kind: m[2] } : { name: s, kind: null };
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
  /**
   * send() 刚内嵌创建的会话 id。创建后 setActiveSession 会触发下面「切会话拉历史」
   * 的 effect，而新会话历史必然为空——那次 setMessages([]) 会把刚乐观插入的提问
   * 和流式占位整个覆盖掉（实测 bug：首次发送"没有效果"，只多了个会话）。
   * 用这个 ref 让 effect 跳过那一次拉取。
   */
  const freshSessionRef = useRef<string | null>(null);
  /** 改名编辑态：正在编辑的会话 id 与草稿标题 */
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  /** 删除二次确认：第一次点 × 只是把它变成「确认」，再点才真删 */
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  /** 初次进入自动建会话只做一次（StrictMode 下 effect 会双跑，不能建两个） */
  const autoCreatedRef = useRef(false);
  /** 待跳转的引用编号（点上标后置位，等右栏渲染出对应条目再滚动）。 */
  const [pendingCite, setPendingCite] = useState<number | null>(null);
  const [citeFlash, setCiteFlash] = useState<number | null>(null);
  const citeRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    api<Project>(`/projects/${projectId}`).then(setProject).catch(() => {});
    api<ChatSession[]>(`/projects/${projectId}/sessions`).then((list) => {
      setSessions(list);
      if (list.length > 0) {
        setActiveSession(list[0].id);
      } else if (!autoCreatedRef.current) {
        // 初次进来默认就有一个可用会话，省掉"先点新会话"这步
        autoCreatedRef.current = true;
        api<ChatSession>(`/projects/${projectId}/sessions`, {
          method: "POST",
          body: JSON.stringify({}),
        })
          .then((s) => {
            setSessions([s]);
            setActiveSession(s.id);
          })
          .catch(() => {});
      }
    });
  }, [projectId]);

  useEffect(() => {
    if (!activeSession) {
      setMessages([]);
      return;
    }
    if (freshSessionRef.current === activeSession) {
      // send() 刚建的会话：本地已有乐观消息，历史为空，拉了反而清屏
      freshSessionRef.current = null;
      setSelected(null);
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

  const renameSession = async (id: string) => {
    const title = editTitle.trim();
    setEditingId(null);
    if (!title) return;
    const s = await api<ChatSession>(`/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
    setSessions((prev) => prev.map((x) => (x.id === id ? s : x)));
  };

  const deleteSession = async (id: string) => {
    setConfirmDelete(null);
    await api(`/sessions/${id}`, { method: "DELETE" });
    const rest = sessions.filter((x) => x.id !== id);
    setSessions(rest);
    if (activeSession === id) setActiveSession(rest[0]?.id ?? null);
    if (rest.length === 0) {
      // 删光后补一个空会话，保持"进来就能直接问"的不变量
      const s = await api<ChatSession>(`/projects/${projectId}/sessions`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setSessions([s]);
      setActiveSession(s.id);
    }
  };

  /**
   * 把第 index 条 assistant 消息接上流；首次发送与重试共用。
   * 按索引而不是「最后一条」定位：重试时那条失败消息未必还在末尾。
   */
  const runAsk = useCallback(
    async (sessionId: string, question: string, index: number) => {
    const patchLast = (
      patch: Partial<DisplayMessage> | ((m: DisplayMessage) => Partial<DisplayMessage>)
    ) =>
      setMessages((prev) =>
        prev.map((m, i) => {
          if (i !== index) return m;
          const p = typeof patch === "function" ? patch(m) : patch;
          return { ...m, ...p };
        })
      );

    await askStream(sessionId, question, {
      onToken: (t) => patchLast((m) => ({ content: m.content + t })),
      onCitations: (c) => patchLast({ citations: c }),
      // 心跳只在首 token 之前有意义，标一次就够
      onPing: () => patchLast((m) => (m.pinged ? {} : { pinged: true })),
      onStage: (stage) => patchLast({ stage }),
      onDone: () => {
        patchLast({ streaming: false });
        setBusy(false);
      },
      onError: (message) => {
        setError(message);
        patchLast({ streaming: false, failed: message });
        setBusy(false);
      },
    });
    },
    []
  );

  const send = async () => {
    if (!input.trim() || busy) return;
    let sessionId = activeSession;
    if (!sessionId) {
      const s = await api<ChatSession>(`/projects/${projectId}/sessions`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      freshSessionRef.current = s.id;
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
      {
        role: "assistant",
        content: "",
        citations: [],
        streaming: true,
        startedAt: Date.now(),
      },
    ]);
    setSelected(null);
    // user 占 messages.length，assistant 紧随其后
    await runAsk(sessionId, question, messages.length + 1);
  };

  /** 重试：复用紧邻的那条提问，把失败的回答就地重置为等待态。 */
  const retry = useCallback(
    async (index: number) => {
      if (busy || !activeSession) return;
      const question = messages[index - 1]?.content;
      if (!question) return;
      setError("");
      setBusy(true);
      setMessages((prev) =>
        prev.map((m, i) =>
          i === index
            ? {
                ...m,
                content: "",
                citations: [],
                streaming: true,
                failed: undefined,
                pinged: false,
                stage: undefined,
                startedAt: Date.now(),
              }
            : m
        )
      );
      await runAsk(activeSession, question, index);
    },
    [busy, activeSession, messages, runAsk]
  );

  /** 右栏显示：选中的回答，否则最后一条带引用的回答 */
  const sourceIndex = useMemo(() => {
    if (selected !== null && messages[selected]?.role === "assistant") return selected;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant" && messages[i].citations.length > 0) return i;
    }
    return null;
  }, [selected, messages]);

  const citations = useMemo(
    () => (sourceIndex !== null ? messages[sourceIndex].citations : []),
    [sourceIndex, messages]
  );

  /** 点上标：先把右栏切到该消息，等对应条目渲染出来再滚动高亮。 */
  const handleCite = useCallback((messageIndex: number, n: number) => {
    setSelected(messageIndex);
    setPendingCite(n);
  }, []);

  useEffect(() => {
    if (pendingCite === null) return;
    const el = citeRefs.current[pendingCite - 1];
    setPendingCite(null);
    if (!el) return; // 编号超出当前引用数，静默忽略
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setCiteFlash(pendingCite - 1);
    const timer = setTimeout(() => setCiteFlash(null), 1000);
    return () => clearTimeout(timer);
  }, [pendingCite, citations]);

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
          {sessions.map((s) =>
            editingId === s.id ? (
              <input
                key={s.id}
                autoFocus
                onFocus={(e) => e.currentTarget.select()}
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                onBlur={() => renameSession(s.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") renameSession(s.id);
                  if (e.key === "Escape") setEditingId(null);
                }}
                className="border border-accent bg-panel px-2.5 py-1.5 text-xs text-ink outline-none"
              />
            ) : (
              <div
                key={s.id}
                onClick={() => setActiveSession(s.id)}
                onDoubleClick={() => {
                  setEditingId(s.id);
                  setEditTitle(s.title);
                }}
                title="双击改名"
                className={`group flex cursor-pointer items-center gap-1 px-3 py-2 text-xs ${
                  s.id === activeSession
                    ? "border-l-2 border-accent bg-panel pl-2.5"
                    : "text-muted hover:text-ink"
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{s.title}</span>
                {confirmDelete === s.id ? (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(s.id);
                    }}
                    onMouseLeave={() => setConfirmDelete(null)}
                    className="flex-none text-[10px] text-danger"
                  >
                    确认?
                  </button>
                ) : (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDelete(s.id);
                    }}
                    title="删除会话"
                    className="hidden flex-none text-[11px] text-faint hover:text-danger group-hover:block"
                  >
                    ×
                  </button>
                )}
              </div>
            )
          )}
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
          <Link href="/rag" className="text-xs text-faint hover:text-ink">
            ← 项目
          </Link>
          <Link
            href={`/rag/projects/${projectId}`}
            className="text-[13px] font-medium hover:text-accent"
          >
            {project?.name ?? "…"}
          </Link>
          <Link
            href={`/rag/projects/${projectId}`}
            className="text-[10px] tracking-wide text-faint hover:text-accent"
          >
            详情 →
          </Link>
          {project && project.status !== "ready" && (
            <span className="border border-danger/40 px-2 py-[2px] text-[10px] tracking-wide text-danger">
              {project.status.toUpperCase()} · 暂不能提问
            </span>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-[30px] pb-4 pt-[26px]">
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
                {/* 首 token 之前走等待态；一有内容立刻切流式渲染 */}
                {m.streaming && !m.content ? (
                  <ThinkingIndicator
                    startedAt={m.startedAt ?? Date.now()}
                    pinged={m.pinged}
                    stage={m.stage}
                  />
                ) : (
                  <div
                    onClick={() => setSelected(i)}
                    className={`cursor-default border bg-panel px-5 py-[18px] text-[13px] leading-[1.95] ${
                      sourceIndex === i ? "border-line" : "border-hair"
                    }`}
                  >
                    <div className="prose prose-sm max-w-none prose-p:my-0 prose-p:mb-3 prose-p:last:mb-0 prose-code:bg-accent/[.08] prose-code:px-1 prose-code:py-px prose-code:text-accent prose-code:before:content-none prose-code:after:content-none prose-pre:overflow-x-auto prose-pre:rounded-none prose-pre:border prose-pre:border-line prose-pre:bg-shade prose-pre:text-ink2">
                      <AnswerBody content={m.content} onCite={(n) => handleCite(i, n)} />
                    </div>
                    {m.streaming && m.content && (
                      <span className="ml-0.5 inline-block h-[13px] w-[7px] animate-pulse bg-accent align-text-bottom" />
                    )}
                  </div>
                )}

                {m.failed && (
                  <div className="flex flex-wrap items-center gap-3 border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-[11px] leading-relaxed text-danger">
                    <span className="min-w-0 flex-1">{m.failed}</span>
                    <button
                      type="button"
                      onClick={() => retry(i)}
                      disabled={busy}
                      className="flex-none border border-danger/40 px-2.5 py-1 text-[10px] tracking-wide text-danger hover:bg-danger/[.08] disabled:opacity-40"
                    >
                      ⟳ 重试
                    </button>
                  </div>
                )}
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

        <div className="flex-none border-t border-line px-[30px] pb-4 pt-3">
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
      <aside className="hidden w-[380px] flex-none flex-col bg-canvas lg:flex xl:w-[472px]">
        <div className="flex flex-none items-center gap-2.5 border-b border-line px-[18px] py-3.5">
          <span className="text-[10px] tracking-label text-dim">
            SOURCES · {citations.length}
          </span>
          <span className="ml-auto text-[10px] tracking-wide text-faint">SORT BY SCORE</span>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3.5">
          {citations.length === 0 && (
            <div className="pt-12 text-center text-[11px] text-faint">
              回答产生的引用会出现在这里
            </div>
          )}
          {citations.map((c, i) => {
            const dir = dirname(c.file_path);
            const { name, kind } = splitSymbol(c.symbol);
            const flash = citeFlash === i;
            return (
              <div
                key={`${c.node_id}-${i}`}
                ref={(el) => {
                  citeRefs.current[i] = el;
                }}
                className={`group bg-panel transition-shadow ${
                  flash
                    ? "border border-accent shadow-[0_0_0_2px_rgba(14,122,69,.25)]"
                    : i === 0
                      ? "border border-accent/40"
                      : "border border-line"
                }`}
              >
                <div className="flex items-start gap-2.5 px-3 py-2.5">
                  <span
                    className={`mt-px flex h-4 w-4 flex-none items-center justify-center text-[10px] ${
                      i === 0 ? "bg-accent text-paper" : "bg-hair text-ink2"
                    }`}
                  >
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[12px] font-medium" title={c.file_path}>
                      {basename(c.file_path)}
                      <span className="font-normal text-dim">
                        :{c.start_line}-{c.end_line}
                      </span>
                    </div>
                    {dir && (
                      <div
                        className="mt-0.5 truncate text-[10px] leading-relaxed text-faint"
                        title={c.file_path}
                      >
                        {middleEllipsis(dir)}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 border-t border-hair px-3 py-1.5 text-[10px] tracking-wide text-dim">
                  {kind && (
                    <span className="flex-none border border-hair bg-shade px-1.5 py-px text-[9px] text-ink2">
                      {kind}
                    </span>
                  )}
                  <span className="truncate" title={c.symbol || undefined}>
                    {name || "—"}
                  </span>
                  <Link
                    href={`/rag/projects/${projectId}?tab=modules`}
                    title="在功能地图中查看所属模块"
                    className="ml-auto flex-none text-accent opacity-0 transition-opacity hover:underline focus:opacity-100 group-hover:opacity-100"
                  >
                    功能地图 →
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      </aside>
    </div>
  );
}
