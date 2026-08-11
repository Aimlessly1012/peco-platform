"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, IndexJob, Project } from "@/lib/api";

const STATUS_BADGE: Record<Project["status"], { label: string; cls: string }> = {
  pending: { label: "待索引", cls: "bg-zinc-100 text-zinc-600" },
  indexing: { label: "索引中", cls: "bg-blue-100 text-blue-700" },
  ready: { label: "就绪", cls: "bg-emerald-100 text-emerald-700" },
  failed: { label: "失败", cls: "bg-red-100 text-red-700" },
};

const STAGE_LABEL: Record<IndexJob["stage"], string> = {
  clone: "拉取代码",
  parse: "解析分块",
  summarize: "生成摘要",
  embed: "向量化",
  graph: "写入图谱",
};

export default function ProjectListPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [jobs, setJobs] = useState<Record<string, IndexJob>>({});
  const [showDialog, setShowDialog] = useState(false);
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

  const triggerIndex = async (id: string) => {
    setError("");
    try {
      await api(`/projects/${id}/index`, { method: "POST" });
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

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">项目</h1>
        <button
          onClick={() => setShowDialog(true)}
          className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700"
        >
          + 录入项目
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {projects.length === 0 ? (
        <div className="rounded-xl border border-dashed py-16 text-center text-zinc-400">
          还没有项目，点击右上角「录入项目」开始
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {projects.map((p) => {
            const badge = STATUS_BADGE[p.status];
            const job = jobs[p.id];
            return (
              <div key={p.id} className="rounded-xl border bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-medium">{p.name}</div>
                    <div className="mt-0.5 break-all text-xs text-zinc-500">{p.git_url}</div>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${badge.cls}`}>
                    {badge.label}
                  </span>
                </div>

                {p.status === "indexing" && job && (
                  <div className="mt-3">
                    <div className="mb-1 flex justify-between text-xs text-zinc-500">
                      <span>{STAGE_LABEL[job.stage]}</span>
                      <span>{job.progress}%</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100">
                      <div
                        className="h-full rounded-full bg-blue-500 transition-all"
                        style={{ width: `${job.progress}%` }}
                      />
                    </div>
                  </div>
                )}

                {p.status === "failed" && job?.error_text && (
                  <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
                    {job.error_text}
                  </div>
                )}

                {p.status === "ready" && (
                  <div className="mt-2 text-xs text-zinc-400">
                    commit {p.last_indexed_commit?.slice(0, 8)}
                  </div>
                )}

                <div className="mt-4 flex gap-2">
                  <a
                    href={`/projects/${p.id}/chat`}
                    className={`rounded-lg px-3 py-1.5 text-sm ${
                      p.status === "ready"
                        ? "bg-zinc-900 text-white hover:bg-zinc-700"
                        : "pointer-events-none bg-zinc-100 text-zinc-400"
                    }`}
                  >
                    聊天
                  </a>
                  <button
                    onClick={() => triggerIndex(p.id)}
                    disabled={p.status === "indexing"}
                    className="rounded-lg border px-3 py-1.5 text-sm hover:bg-zinc-50 disabled:opacity-40"
                  >
                    {p.status === "pending" ? "开始索引" : "重新索引"}
                  </button>
                  <button
                    onClick={() => remove(p)}
                    className="ml-auto rounded-lg px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
                  >
                    删除
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

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

function NewProjectDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({ name: "", git_url: "", git_token: "", default_branch: "" });
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
      await api(`/projects/${project.id}/index`, { method: "POST" });
      onCreated();
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  const field = "w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-300";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold">录入项目</h2>
        <div className="space-y-3">
          <input className={field} placeholder="项目名称 *" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className={field} placeholder="Git 地址（https）*" value={form.git_url}
            onChange={(e) => setForm({ ...form, git_url: e.target.value })} />
          <input className={field} type="password" placeholder="访问 Token（私有仓必填）" value={form.git_token}
            onChange={(e) => setForm({ ...form, git_token: e.target.value })} />
          <input className={field} placeholder="分支（默认主分支）" value={form.default_branch}
            onChange={(e) => setForm({ ...form, default_branch: e.target.value })} />
        </div>
        {error && <div className="mt-3 text-sm text-red-600">{error}</div>}
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border px-4 py-2 text-sm hover:bg-zinc-50">
            取消
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white hover:bg-zinc-700 disabled:opacity-50"
          >
            {submitting ? "提交中…" : "录入并开始索引"}
          </button>
        </div>
      </div>
    </div>
  );
}
