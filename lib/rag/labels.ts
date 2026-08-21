/** 各处共用的中文标签、终端风徽标样式与格式化工具。 */
import type { IndexJob, JobStage, ModuleKind, Project } from "./api";

/** 六阶段顺序（M3：graph 之后新增 report）。 */
export const STAGE_ORDER: JobStage[] = [
  "clone",
  "parse",
  "summarize",
  "embed",
  "graph",
  "report",
];

export const STAGE_LABEL: Record<JobStage, string> = {
  clone: "拉取代码",
  parse: "解析分块",
  summarize: "生成摘要",
  embed: "向量化",
  graph: "写入图谱",
  report: "生成报告",
};

/** 后端若返回未知阶段，直接回显原值而不是 undefined。 */
export function stageLabel(stage: string): string {
  return STAGE_LABEL[stage as JobStage] ?? stage;
}

/** 项目状态：设计稿的终端风徽标（方块字形 + 边框色）。 */
export const PROJECT_STATUS_BADGE: Record<
  Project["status"],
  { label: string; cls: string; glyph: string }
> = {
  pending: { label: "PENDING 待索引", cls: "text-muted border-line", glyph: "○" },
  indexing: {
    label: "INDEXING",
    cls: "text-accent border-accent/40 bg-accent/[.08]",
    glyph: "◐",
  },
  ready: { label: "READY 就绪", cls: "text-accent border-accent/40", glyph: "●" },
  failed: { label: "FAILED 失败", cls: "text-danger border-danger/40", glyph: "▲" },
};

export const JOB_STATUS_BADGE: Record<
  IndexJob["status"],
  { label: string; cls: string }
> = {
  running: { label: "RUNNING 进行中", cls: "text-accent border-accent/40" },
  succeeded: { label: "OK 成功", cls: "text-accent border-accent/40" },
  failed: { label: "FAILED 失败", cls: "text-danger border-danger/40" },
};

export function jobStatusBadge(status: string): { label: string; cls: string } {
  return (
    JOB_STATUS_BADGE[status as IndexJob["status"]] ?? {
      label: status.toUpperCase(),
      cls: "text-muted border-line",
    }
  );
}

/** 模块 kind 的分组顺序、中文名与终端风配色。 */
export const MODULE_KIND_ORDER: ModuleKind[] = ["page", "api", "shared", "dir"];

export const MODULE_KIND_META: Record<
  ModuleKind,
  { label: string; hint: string; cls: string }
> = {
  page: {
    label: "PAGE 页面",
    hint: "前端路由页面模块",
    cls: "text-accent border-accent/40 bg-accent/[.06]",
  },
  api: {
    label: "API 接口",
    hint: "后端 API 路由模块",
    cls: "text-ink2 border-ink/25 bg-shade",
  },
  shared: {
    label: "SHARED 公共",
    hint: "跨模块复用代码",
    cls: "text-muted border-line bg-shade",
  },
  dir: {
    label: "DIR 目录",
    hint: "按目录聚合的模块",
    cls: "text-faint border-hair bg-shade",
  },
};

export function moduleKindMeta(kind: string) {
  return (
    MODULE_KIND_META[kind as ModuleKind] ?? {
      label: (kind || "other").toUpperCase(),
      hint: "未归类模块",
      cls: "text-faint border-hair bg-shade",
    }
  );
}

/** 索引统计键的中文名；未知键回显原键。 */
const STAT_LABEL: Record<string, string> = {
  files_parsed: "解析文件",
  files_skipped: "跳过文件",
  chunks: "代码块",
  modules: "模块数",
  api_edges: "接口调用边",
  api_warnings: "接口匹配告警",
  router_fallback: "路由降级",
  summaries_new: "新增摘要",
  summaries_cached: "命中缓存摘要",
  embedded: "已向量化",
  embedded_new: "新增向量",
  embedded_cached: "命中缓存向量",
  sequences_ok: "时序图成功",
  sequences_fallback: "时序图降级",
};

export function statLabel(key: string): string {
  return STAT_LABEL[key] ?? key;
}

/** stats_json 里取数值，兼容后端可能的键名差异。 */
export function statNumber(
  stats: Record<string, number | string | boolean> | null | undefined,
  ...keys: string[]
): number {
  for (const k of keys) {
    const v = stats?.[k];
    if (typeof v === "number") return v;
    if (typeof v === "string" && v !== "" && !Number.isNaN(Number(v))) {
      return Number(v);
    }
  }
  return 0;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(
    d.getHours()
  )}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 任务耗时；未结束的任务按「至今」计算。 */
export function formatDuration(
  startedAt: string | null | undefined,
  finishedAt: string | null | undefined
): string {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "—";
  const sec = Math.round((end - start) / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}
