"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import StageBar from "@/components/StageBar";
import { api, IndexDepth, IndexJob, Project } from "@/lib/api";
import { PROJECT_STATUS_BADGE, statNumber } from "@/lib/labels";

const COLS = "grid-cols-[14px_1fr_150px_150px_176px]";

type Filter = "all" | "indexing" | "failed";

export default function ProjectListPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [jobs, setJobs] = useState<Record<string, IndexJob>>({});
  const [showDialog, setShowDialog] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api<Project[]>("/projects");
      setProjects(list);
      const active = list.filter((p) => p.status === "indexing" || p.status === "failed");
      const jobEntries = await Promise.all(
        active.map(async (p) => {
          try {
            const job = await api<IndexJob>(`/projects/${p.id}/jobs/latest`);
            return [p.id, job] as const;
          } catch {
            return null;
          }
        })
      );
      setJobs(Object.fromEntries(jobEntries.filter(Boolean) as [string, IndexJob][]));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 2000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  /** 重新索引保持项目原有深度：fast 项目不会因为点一下 ⟳ 就产生 LLM 成本。 */
  const triggerIndex = async (p: Project) => {
    setError("");
    try {
      const query = p.index_depth === "fast" ? "?depth=fast" : "";
      await api(`/projects/${p.id}/index${query}`, { method: "POST" });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (p: Project) => {
    if (!confirm(`确认删除项目「${p.name}」？将同时删除其索引数据与本地副本。`)) return;
    try {
      await api(`/projects/${p.id}`, { method: "DELETE" });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const shown = useMemo(
    () => (filter === "all" ? projects : projects.filter((p) => p.status === filter)),
    [projects, filter]
  );
  const indexingCount = projects.filter((p) => p.status === "indexing").length;

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左栏：统计与筛选 */}
      <aside className="hidden w-[212px] flex-none flex-col gap-7 border-r border-line bg-canvas px-5 py-6 md:flex">
        <div className="flex flex-col gap-1.5">
          <div className="text-[10px] tracking-label text-dim">PROJECTS</div>
          <div className="text-[38px] font-semibold leading-none">
            {String(projects.length).padStart(2, "0")}
          </div>
          <div className="text-[11px] text-muted">
            {indexingCount > 0 ? `${indexingCount} 正在索引` : "全部空闲"}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-label text-dim">FILTER</div>
          {(["all", "indexing", "failed"] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`flex gap-2 text-left text-xs ${
                filter === f ? "font-medium text-accent" : "text-muted hover:text-ink"
              }`}
            >
              <span>{filter === f ? "▸" : " "}</span>
              <span>{f}</span>
            </button>
          ))}
        </div>

        <div className="mt-auto text-[11px] leading-relaxed text-faint">
          MCP
          <br />
          <a href="/mcp-guide" className="text-muted hover:text-accent">
            localhost:8001/mcp
          </a>
        </div>
      </aside>

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-7 py-6">
        <div className="flex items-end justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-[22px] font-semibold">项目</h1>
            <span className="text-[11px] text-dim">
              $ ls --status<span className="text-accent">_</span>
            </span>
          </div>
          <button
            onClick={() => setShowDialog(true)}
            className="border border-accent bg-accent/[.06] px-4 py-2 text-xs font-medium tracking-wide text-accent hover:bg-accent/[.12]"
          >
            + 录入项目
          </button>
        </div>

        {error && (
          <div className="border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}

        {shown.length === 0 ? (
          <div className="border border-dashed border-line py-16 text-center text-sm text-faint">
            {projects.length === 0
              ? "还没有项目，点击右上角「录入项目」开始"
              : `没有 ${filter} 状态的项目`}
          </div>
        ) : (
          <div className="flex flex-col overflow-x-auto border border-line bg-panel">
            <div
              className={`grid ${COLS} min-w-[860px] gap-4 border-b border-line bg-shade px-4 py-[9px] text-[10px] tracking-label text-dim`}
            >
              <span />
              <span>PROJECT</span>
              <span>COMMIT</span>
              <span>STATUS</span>
              <span className="text-right">ACTIONS</span>
            </div>

            {shown.map((p) => {
              const s = PROJECT_STATUS_BADGE[p.status];
              const job = jobs[p.id];
              const isIndexing = p.status === "indexing" && !!job;
              const isFailed = p.status === "failed";
              return (
                <div
                  key={p.id}
                  className={`min-w-[860px] border-b border-hair px-4 py-4 last:border-b-0 ${
                    isIndexing ? "bg-accent/[.04]" : isFailed ? "bg-danger/[.03]" : ""
                  }`}
                >
                  <div className={`grid ${COLS} items-center gap-4`}>
                    <span
                      className={`text-xs ${
                        isFailed
                          ? "text-danger"
                          : p.status === "pending"
                            ? "text-faint"
                            : "text-accent"
                      }`}
                    >
                      {s.glyph}
                    </span>
                    <div className="min-w-0">
                      <a
                        href={`/projects/${p.id}`}
                        className="text-[15px] font-medium hover:text-accent"
                      >
                        {p.name}
                      </a>
                      <div className="mt-[3px] truncate text-[11px] text-muted">
                        {p.git_url}
                        {p.default_branch ? ` · ${p.default_branch}` : ""}
                        {p.index_depth === "fast" && (
                          <span className="ml-1.5 text-accent" title="快速模式索引，未生成深度理解">
                            · FAST
                          </span>
                        )}
                      </div>
                    </div>
                    <span className="text-xs text-muted">
                      {p.last_indexed_commit ? p.last_indexed_commit.slice(0, 8) : "—"}
                    </span>
                    <span
                      className={`justify-self-start border px-2 py-[3px] text-[11px] tracking-wide ${s.cls}`}
                    >
                      {p.status === "indexing" && job ? `INDEXING ${job.progress}%` : s.label}
                    </span>
                    <div className="flex justify-end gap-2 text-[11px]">
                      <a
                        href={`/projects/${p.id}`}
                        className="border border-line px-[10px] py-[5px] text-muted hover:border-ink hover:text-ink"
                      >
                        详情
                      </a>
                      {p.status === "ready" ? (
                        <a
                          href={`/projects/${p.id}/chat`}
                          className="bg-ink px-[10px] py-[5px] font-medium text-paper"
                        >
                          聊天
                        </a>
                      ) : (
                        <span className="border border-hair px-[10px] py-[5px] text-faint">
                          聊天
                        </span>
                      )}
                      <button
                        onClick={() => triggerIndex(p)}
                        disabled={p.status === "indexing"}
                        title={
                          p.status === "pending"
                            ? "开始索引"
                            : p.index_depth === "fast"
                              ? "重新索引（保持快速模式）"
                              : "重新索引"
                        }
                        className="border border-line px-[10px] py-[5px] text-muted hover:text-ink disabled:opacity-40"
                      >
                        {p.status === "pending" ? "开始索引" : "⟳"}
                      </button>
                      <button
                        onClick={() => remove(p)}
                        title="删除项目"
                        className="px-1 text-danger hover:underline"
                      >
                        ✕
                      </button>
                    </div>
                  </div>

                  {isIndexing && (
                    <div className="mt-3.5 flex items-center gap-3.5">
                      <StageBar stage={job.stage} progress={job.progress} />
                      <span className="whitespace-nowrap text-[11px] text-muted">
                        {statNumber(job.stats_json, "embedded", "embedded_new")}/
                        {statNumber(job.stats_json, "chunks")} chunk
                        {statNumber(job.stats_json, "embedded_cached")
                          ? ` · cached ${statNumber(job.stats_json, "embedded_cached")}`
                          : ""}
                      </span>
                    </div>
                  )}

                  {isFailed && job?.error_text && (
                    <div className="mt-3 border-l-2 border-danger bg-danger/[.05] px-3 py-2 text-[11px] leading-relaxed text-danger">
                      stage={job.stage} · {job.error_text}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="mt-auto text-[11px] text-faint">
          每 2s 轮询 /projects · 索引完成后状态自动转「就绪」
        </div>
      </div>

      {showDialog && (
        <NewProjectDialog
          onClose={() => setShowDialog(false)}
          onCreated={() => {
            setShowDialog(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}

const DEPTHS: { key: IndexDepth; title: string; hint: string }[] = [
  {
    key: "deep",
    title: "深度理解",
    hint: "完整 AI 分析：文件摘要、需求文档、时序图、数据流图",
  },
  {
    key: "fast",
    title: "快速录入",
    hint: "快速模式零 AI 成本，仅结构与代码检索",
  },
];

function NewProjectDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({ name: "", git_url: "", git_token: "", default_branch: "" });
  const [depth, setDepth] = useState<IndexDepth>("deep");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!form.name || !form.git_url) {
      setError("名称和 Git 地址必填");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const project = await api<{ id: string }>("/projects", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          git_url: form.git_url,
          git_token: form.git_token || null,
          default_branch: form.default_branch || null,
        }),
      });
      await api(`/projects/${project.id}/index?depth=${depth}`, { method: "POST" });
      onCreated();
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  const label = "text-[10px] tracking-wide text-dim";
  const field =
    "w-full border border-line bg-shade px-3 py-2 text-[12.5px] focus:border-accent focus:bg-panel";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/[.15] p-4">
      <div className="w-full max-w-[520px] border border-ink bg-panel shadow-[8px_8px_0_rgba(23,23,26,.07)]">
        <div className="flex items-center gap-2.5 border-b border-line bg-shade px-[18px] py-3">
          <span className="block h-2 w-2 bg-accent" />
          <span className="text-[10px] tracking-label text-dim">NEW PROJECT</span>
        </div>
        <div className="px-[26px] py-6">
          <h2 className="mb-5 text-[19px] font-semibold">录入项目</h2>
          <div className="flex flex-col gap-[15px]">
            <div className="flex flex-col gap-1.5">
              <span className={label}>
                NAME <span className="text-accent">*</span>
              </span>
              <input
                className={field}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <span className={label}>
                GIT URL (HTTPS) <span className="text-accent">*</span>
              </span>
              <input
                className={field}
                placeholder="https://github.com/acme/repo.git"
                value={form.git_url}
                onChange={(e) => setForm({ ...form, git_url: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-[13px]">
              <div className="flex flex-col gap-1.5">
                <span className={label}>TOKEN</span>
                <input
                  className={field}
                  type="password"
                  placeholder="私有仓必填"
                  value={form.git_token}
                  onChange={(e) => setForm({ ...form, git_token: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className={label}>BRANCH</span>
                <input
                  className={field}
                  placeholder="默认主分支"
                  value={form.default_branch}
                  onChange={(e) => setForm({ ...form, default_branch: e.target.value })}
                />
              </div>
            </div>
          </div>

          <div className="mt-[15px] flex flex-col gap-1.5">
            <span className={label}>DEPTH 索引深度</span>
            <div className="grid grid-cols-2 gap-[13px]">
              {DEPTHS.map((d) => {
                const on = depth === d.key;
                return (
                  <button
                    key={d.key}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setDepth(d.key)}
                    className={`border px-3 py-2.5 text-left ${
                      on
                        ? "border-accent bg-accent/[.06]"
                        : "border-line bg-shade hover:border-ink"
                    }`}
                  >
                    <span className="flex items-center gap-2 text-[12px] font-medium">
                      <span
                        className={`block h-[7px] w-[7px] ${on ? "bg-accent" : "bg-line"}`}
                      />
                      {d.title}
                      {d.key === "deep" && (
                        <span className="text-[10px] font-normal text-dim">默认</span>
                      )}
                    </span>
                    <span className="mt-1 block text-[10px] leading-relaxed text-muted">
                      {d.hint}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {error && <div className="mt-3 text-xs text-danger">{error}</div>}

          <div className="mt-4 flex items-center gap-2 text-[11px] text-muted">
            <span className="block h-[5px] w-[5px] bg-accent" />
            录入后立即开始索引
            {depth === "fast" && "（快速模式，稍后可在详情页生成深度理解）"}
          </div>

          <div className="mt-5 flex justify-end gap-[9px]">
            <button
              onClick={onClose}
              className="border border-line px-4 py-[9px] text-[11px] tracking-wide text-muted hover:text-ink"
            >
              取消
            </button>
            <button
              onClick={submit}
              disabled={submitting}
              className="bg-ink px-4 py-[9px] text-[11px] font-medium tracking-wide text-paper disabled:opacity-50"
            >
              {submitting ? "提交中…" : "录入并开始索引"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
