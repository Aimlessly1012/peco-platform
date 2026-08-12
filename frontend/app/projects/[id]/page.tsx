"use client";

import dynamic from "next/dynamic";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import CopyButton from "@/components/CopyButton";
import StageBar from "@/components/StageBar";
import {
  api,
  IndexJob,
  isNotFound,
  ModuleInfo,
  ModuleMap,
  Project,
  UnderstandingReport,
} from "@/lib/api";
import { buildModuleMindmap, MODULE_MINDMAP_FILE_LIMIT } from "@/lib/mermaid";
import {
  formatDateTime,
  formatDuration,
  jobStatusBadge,
  MODULE_KIND_ORDER,
  moduleKindMeta,
  PROJECT_STATUS_BADGE,
  stageLabel,
  statLabel,
} from "@/lib/labels";
import { isMockMode, MOCK_JOBS, MOCK_MODULES, MOCK_REPORT } from "@/lib/mock";

const diagramLoading = (label: string) => () => (
  <div className="border border-line bg-panel px-4 py-10 text-center text-[11px] tracking-wide text-faint">
    {label}
  </div>
);

/** mermaid 体积大且强依赖浏览器 API：仅在客户端动态加载（关闭 SSR）。 */
const MermaidDiagram = dynamic(() => import("@/components/MermaidDiagram"), {
  ssr: false,
  loading: diagramLoading("LOADING DIAGRAM…"),
});

/** markmap 同理（markmap-lib + markmap-view + d3，只在需要时进包）。 */
const MarkmapView = dynamic(() => import("@/components/MarkmapView"), {
  ssr: false,
  loading: diagramLoading("LOADING FEATURE MAP…"),
});

const TABS = [
  { key: "understanding", label: "项目理解" },
  { key: "modules", label: "功能地图" },
  { key: "jobs", label: "索引记录" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

type ReportState = "loading" | "ok" | "empty" | "error";

const TAB_KEYS = TABS.map((t) => t.key) as readonly string[];

/** 与 chat 页共用的 markdown 排版（终端风：无圆角、代码块浅底）。 */
const PROSE =
  "prose prose-sm max-w-none prose-headings:font-semibold prose-p:my-0 prose-p:mb-3 prose-p:last:mb-0 prose-li:my-0.5 prose-code:bg-accent/[.08] prose-code:px-1 prose-code:py-px prose-code:text-accent prose-code:before:content-none prose-code:after:content-none prose-pre:overflow-x-auto prose-pre:rounded-none prose-pre:border prose-pre:border-line prose-pre:bg-shade prose-pre:text-ink2";

export default function ProjectDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: projectId } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [job, setJob] = useState<IndexJob | null>(null);
  const [tab, setTab] = useState<TabKey>("understanding");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [missing, setMissing] = useState(false);
  const [mock, setMock] = useState(false);
  /** 索引由「进行中」跃迁为结束时自增，驱动报告/模块页签重新拉取。 */
  const [reloadKey, setReloadKey] = useState(0);
  /** 模块地图提到父组件：功能地图页签与项目理解页签的子导图共用同一份数据。 */
  const [modules, setModules] = useState<ModuleInfo[] | null>(null);
  const [modulesError, setModulesError] = useState("");
  /** 报告同样提到父组件：M6 后结构导图归功能地图页签，两个页签都要读它。 */
  const [report, setReport] = useState<UnderstandingReport | null>(null);
  const [reportState, setReportState] = useState<ReportState>("loading");
  const [reportError, setReportError] = useState("");

  // 初始页签支持 ?tab=（聊天页 SOURCES 卡片链到 ?tab=modules）
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const t = q.get("tab");
    if (t && TAB_KEYS.includes(t)) setTab(t as TabKey);
    if (isMockMode()) setMock(true);
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    let wasIndexing = false;

    const tick = async () => {
      try {
        const p = await api<Project>(`/projects/${projectId}`);
        if (stopped) return;
        setProject(p);
        setError("");
        // 索引刚结束：报告与模块数据已更新，让对应页签重新取一次
        const indexing = p.status === "indexing";
        if (wasIndexing && !indexing) setReloadKey((k) => k + 1);
        wasIndexing = indexing;
        try {
          const latest = await api<IndexJob>(`/projects/${projectId}/jobs/latest`);
          if (!stopped) setJob(latest);
        } catch {
          if (!stopped) setJob(null);
        }
      } catch (e) {
        if (stopped) return;
        // 项目已被删除或 id 不存在：停止轮询，避免每 2 秒重复报错
        if (isNotFound(e)) {
          setMissing(true);
          if (timer) clearInterval(timer);
        } else {
          setError((e as Error).message);
        }
      }
    };

    tick();
    timer = setInterval(tick, 2000);
    return () => {
      stopped = true;
      if (timer) clearInterval(timer);
    };
  }, [projectId]);

  useEffect(() => {
    let stopped = false;
    if (mock) {
      setModules(MOCK_MODULES.modules);
      return;
    }
    setModules(null);
    setModulesError("");
    api<ModuleMap>(`/projects/${projectId}/modules`)
      .then((m) => {
        if (!stopped) setModules(m.modules ?? []);
      })
      .catch((e) => {
        if (!stopped) setModulesError((e as Error).message);
      });
    return () => {
      stopped = true;
    };
  }, [projectId, mock, reloadKey]);

  useEffect(() => {
    let stopped = false;
    if (mock) {
      setReport(MOCK_REPORT);
      setReportState("ok");
      return;
    }
    setReportState("loading");
    setReportError("");
    api<UnderstandingReport>(`/projects/${projectId}/report`)
      .then((r) => {
        if (stopped) return;
        setReport(r);
        setReportState("ok");
      })
      .catch((e) => {
        if (stopped) return;
        if (isNotFound(e)) {
          setReport(null);
          setReportState("empty");
        } else {
          setReportError((e as Error).message);
          setReportState("error");
        }
      });
    return () => {
      stopped = true;
    };
  }, [projectId, mock, reloadKey]);

  const runIndex = useCallback(
    async (query: string, message: string) => {
      setError("");
      setNotice("");
      try {
        await api(`/projects/${projectId}/index${query}`, { method: "POST" });
        setNotice(message);
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [projectId]
  );

  const isFast = project?.index_depth === "fast";

  /** 重新索引保持当前深度，不让 fast 项目意外产生 LLM 成本。 */
  const reindex = useCallback(
    () =>
      runIndex(
        isFast ? "?depth=fast" : "",
        isFast
          ? "已触发重新索引（保持快速模式）。"
          : "已触发重新索引，完成后本页自动刷新报告。"
      ),
    [runIndex, isFast]
  );

  /** fast → deep 补跑：代码没变时摘要与向量全走缓存，只补 LLM 摘要与报告。 */
  const deepen = useCallback(
    () =>
      runIndex(
        "?depth=deep&mode=auto",
        "已开始生成深度理解，完成后本页自动刷新报告。"
      ),
    [runIndex]
  );

  if (missing) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-7">
        <div className="border border-dashed border-line px-10 py-14 text-center">
          <div className="text-sm text-muted">项目不存在或已被删除</div>
          <a
            href="/"
            className="mt-5 inline-block bg-ink px-4 py-2 text-[11px] tracking-wide text-paper"
          >
            ← 返回项目列表
          </a>
        </div>
      </div>
    );
  }

  const badge = project ? PROJECT_STATUS_BADGE[project.status] : null;
  const indexing = project?.status === "indexing";

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左栏：项目元信息与操作 */}
      <aside className="hidden w-[212px] flex-none flex-col gap-6 overflow-y-auto border-r border-line bg-canvas px-5 py-6 md:flex">
        <div className="flex flex-col gap-2">
          <a href="/" className="text-[11px] text-faint hover:text-ink">
            ← 项目
          </a>
          <div className="break-words text-[17px] font-semibold leading-tight">
            {project?.name ?? "…"}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {badge && (
              <span
                className={`w-fit border px-2 py-[3px] text-[10px] tracking-wide ${badge.cls}`}
              >
                {badge.glyph} {badge.label}
              </span>
            )}
            {isFast && (
              <span
                className="w-fit border border-line px-2 py-[3px] text-[10px] tracking-wide text-ink2"
                title="快速模式索引：零 AI 成本，未生成深度理解"
              >
                FAST
              </span>
            )}
          </div>
        </div>

        <dl className="flex flex-col gap-3 text-[11px]">
          <div>
            <dt className="tracking-label text-dim">GIT</dt>
            <dd className="mt-1 break-all text-muted">{project?.git_url ?? "—"}</dd>
          </div>
          <div>
            <dt className="tracking-label text-dim">BRANCH</dt>
            <dd className="mt-1 text-muted">{project?.default_branch || "默认主分支"}</dd>
          </div>
          <div>
            <dt className="tracking-label text-dim">COMMIT</dt>
            <dd className="mt-1 text-muted">
              {project?.last_indexed_commit?.slice(0, 8) ?? "—"}
            </dd>
          </div>
        </dl>

        <div className="flex flex-col gap-2">
          <a
            href={`/projects/${projectId}/chat`}
            className={`px-3 py-2 text-center text-[11px] tracking-wide ${
              project?.status === "ready"
                ? "bg-ink font-medium text-paper"
                : "pointer-events-none border border-hair text-faint"
            }`}
          >
            聊天
          </a>
          {isFast && (
            <button
              onClick={deepen}
              disabled={indexing}
              className="border border-accent bg-accent/[.06] px-3 py-2 text-[11px] font-medium tracking-wide text-accent hover:bg-accent/[.12] disabled:opacity-40"
            >
              生成深度理解
            </button>
          )}
          <button
            onClick={reindex}
            disabled={indexing}
            className="border border-line px-3 py-2 text-[11px] tracking-wide text-muted hover:border-ink hover:text-ink disabled:opacity-40"
          >
            {indexing ? "索引中…" : isFast ? "⟳ 重新索引 (fast)" : "⟳ 重新索引"}
          </button>
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
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto px-7 py-6">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[22px] font-semibold md:hidden">{project?.name ?? "…"}</h1>
          <span className="hidden text-[11px] text-dim md:block">
            $ cat project --understanding<span className="text-accent">_</span>
          </span>
        </div>

        {/* 小屏没有左栏，操作入口在这里补齐 */}
        <div className="mt-3 flex flex-wrap items-center gap-2 md:hidden">
          <a href="/" className="text-[11px] text-faint hover:text-ink">
            ← 项目
          </a>
          {badge && (
            <span className={`border px-2 py-[3px] text-[10px] tracking-wide ${badge.cls}`}>
              {badge.glyph} {badge.label}
            </span>
          )}
          {isFast && (
            <span className="border border-line px-2 py-[3px] text-[10px] tracking-wide text-ink2">
              FAST
            </span>
          )}
          <a
            href={`/projects/${projectId}/chat`}
            className={`ml-auto px-3 py-1.5 text-[11px] tracking-wide ${
              project?.status === "ready"
                ? "bg-ink font-medium text-paper"
                : "pointer-events-none border border-hair text-faint"
            }`}
          >
            聊天
          </a>
          {isFast && (
            <button
              onClick={deepen}
              disabled={indexing}
              className="border border-accent bg-accent/[.06] px-3 py-1.5 text-[11px] font-medium tracking-wide text-accent hover:bg-accent/[.12] disabled:opacity-40"
            >
              生成深度理解
            </button>
          )}
          <button
            onClick={reindex}
            disabled={indexing}
            className="border border-line px-3 py-1.5 text-[11px] tracking-wide text-muted hover:border-ink hover:text-ink disabled:opacity-40"
          >
            {indexing ? "索引中…" : isFast ? "⟳ 重新索引 (fast)" : "⟳ 重新索引"}
          </button>
        </div>

        {indexing && job && (
          <div className="mt-4 flex items-center gap-3.5">
            <StageBar stage={job.stage} progress={job.progress} />
            <span className="whitespace-nowrap text-[11px] text-muted">
              {stageLabel(job.stage)}
            </span>
          </div>
        )}

        {error && (
          <div className="mt-4 border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}
        {notice && (
          <div className="mt-4 border-l-2 border-accent bg-accent/[.06] px-3 py-2 text-xs text-accent">
            {notice}
          </div>
        )}

        <div className="mt-5 flex gap-0 border-b border-line" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={`-mb-px border-b-2 px-4 py-2 text-[11.5px] tracking-wide ${
                tab === t.key
                  ? "border-accent font-medium text-ink"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="py-5">
          {tab === "understanding" && (
            <UnderstandingTab
              report={report}
              state={reportState}
              error={reportError}
              indexing={!!indexing}
              onReindex={reindex}
              onDeepen={deepen}
            />
          )}
          {tab === "modules" && (
            <ModulesTab
              modules={modules}
              error={modulesError}
              structureMermaid={report?.mindmap_mermaid ?? ""}
              dataflowMermaid={report?.dataflow_mermaid ?? ""}
            />
          )}
          {tab === "jobs" && <JobsTab projectId={projectId} mock={mock} />}
        </div>
      </div>
    </div>
  );
}

function Loading({ text = "LOADING…" }: { text?: string }) {
  return (
    <div className="border border-line bg-panel py-16 text-center text-[11px] tracking-wide text-faint">
      {text}
    </div>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <div className="border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-xs text-danger">
      {message}
    </div>
  );
}

function SectionLabel({ text, extra }: { text: string; extra?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="block h-[9px] w-[9px] bg-accent" />
      <span className="text-[10px] tracking-label text-dim">
        {text}
        {extra ? ` · ${extra}` : ""}
      </span>
    </div>
  );
}

/**
 * 页签一：项目理解。
 * M5 起为四件套：需求文档 + 顶层导图（Project→Module）+ 模块数据流图 + 时序图，
 * 外加模块子导图——由已加载的模块地图数据在前端即时拼装，不发额外请求。
 */
function UnderstandingTab({
  report,
  state,
  error,
  indexing,
  onReindex,
  onDeepen,
}: {
  report: UnderstandingReport | null;
  state: ReportState;
  error: string;
  indexing: boolean;
  onReindex: () => void;
  onDeepen: () => void;
}) {
  if (state === "loading") return <Loading text="LOADING REPORT…" />;
  if (state === "error") return <ErrorCard message={error} />;

  if (state === "empty" || !report) {
    return (
      <div className="border border-dashed border-line px-6 py-14 text-center">
        <div className="text-sm text-muted">
          {indexing ? "正在索引，报告尚未生成" : "该项目还没有理解报告"}
        </div>
        <div className="mx-auto mt-2 max-w-md text-[11px] leading-relaxed text-faint">
          {indexing
            ? "报告在索引的最后一个阶段「生成报告」产出，索引完成后本页会自动刷新。"
            : "报告在索引的「生成报告」阶段产出。如果项目最后一次索引早于该功能上线，重新索引一次即可生成需求逻辑文档、功能思维导图与核心流程时序图。"}
        </div>
        {!indexing && (
          <button
            onClick={onReindex}
            className="mt-5 bg-ink px-4 py-2 text-[11px] tracking-wide text-paper"
          >
            重新索引以生成报告
          </button>
        )}
      </div>
    );
  }

  const reportIsFast = report.depth === "fast";

  return (
    <div className="flex flex-col gap-6">
      <div className="text-[10px] tracking-wide text-faint">
        GENERATED {formatDateTime(report.generated_at)}
        {report.depth ? ` · DEPTH ${report.depth.toUpperCase()}` : ""}
      </div>

      {reportIsFast && (
        <div className="flex flex-wrap items-center gap-3 border border-line bg-shade px-4 py-3">
          <span className="border border-line bg-panel px-2 py-[3px] text-[10px] tracking-wide text-ink2">
            FAST
          </span>
          <span className="min-w-0 flex-1 text-[11px] leading-relaxed text-muted">
            快速模式产物：只有结构类图与代码检索，没有 AI 生成的需求文档与时序图。
            生成深度理解会复用已有的解析与向量缓存，只补 AI 部分。
          </span>
          <button
            onClick={onDeepen}
            disabled={indexing}
            className="border border-accent bg-accent/[.06] px-3 py-1.5 text-[11px] font-medium tracking-wide text-accent hover:bg-accent/[.12] disabled:opacity-40"
          >
            {indexing ? "索引中…" : "生成深度理解"}
          </button>
        </div>
      )}

      <section className="flex flex-col gap-2.5">
        <SectionLabel text="FEATURE MAP 需求功能思维导图" />
        {report.feature_map_markdown?.trim() ? (
          <MarkmapView
            title="需求功能思维导图"
            subtitle="产品定位 → 功能域 → 功能点，初始展开到功能域层"
            markdown={report.feature_map_markdown}
          />
        ) : (
          <>
            <div className="border-l-2 border-line bg-shade px-3 py-2 text-[11px] leading-relaxed text-muted">
              这份报告生成于功能导图上线之前，下面展示的是旧版结构导图（模块视角）。
              重新索引即可获取需求功能导图。
            </div>
            <MermaidDiagram
              title="功能思维导图（旧版结构视角）"
              subtitle="由图谱中的 项目 → 模块 结构程序化生成"
              code={report.mindmap_mermaid || ""}
            />
          </>
        )}
      </section>

      {report.business_flows?.length ? (
        <section className="flex flex-col gap-2.5">
          <SectionLabel
            text="BUSINESS FLOWS 业务流程图"
            extra={String(report.business_flows.length)}
          />
          <div className="flex flex-col gap-3">
            {report.business_flows.map((f, i) => (
              <MermaidDiagram
                key={`${f.title || "flow"}-${i}`}
                title={f.title || `业务流程 ${i + 1}`}
                subtitle="需求视角的业务链路"
                code={f.mermaid || ""}
                fallbackText={f.fallback_text}
              />
            ))}
          </div>
        </section>
      ) : null}

      <section className="flex flex-col gap-2.5">
        <SectionLabel text="REQUIREMENT DOC 需求逻辑文档" />
        <div className="border border-line bg-panel">
          <div className="flex items-center gap-2 border-b border-line bg-shade px-4 py-2.5">
            <span className="text-[12.5px] font-medium">需求逻辑文档</span>
            <CopyButton
              text={report.doc_markdown || ""}
              label="COPY MD"
              className="ml-auto"
            />
          </div>
          <div className="p-5">
            {report.doc_markdown?.trim() ? (
              <div className={PROSE}>
                <ReactMarkdown>{report.doc_markdown}</ReactMarkdown>
              </div>
            ) : (
              <div className="py-8 text-center text-[11px] leading-relaxed text-faint">
                {reportIsFast
                  ? "快速模式不生成需求文档，点上方「生成深度理解」即可补齐"
                  : "文档内容为空"}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-2.5">
        <SectionLabel
          text="SEQUENCES 核心流程时序图"
          extra={String(report.sequences?.length ?? 0)}
        />
        {report.sequences?.length ? (
          <div className="flex flex-col gap-3">
            {report.sequences.map((s, i) => (
              <MermaidDiagram
                key={`${s.module_key || "seq"}-${i}`}
                title={s.module_name || s.module_key}
                subtitle={s.module_key}
                code={s.mermaid || ""}
                fallbackText={s.fallback_text}
              />
            ))}
          </div>
        ) : (
          <div className="border border-dashed border-line py-10 text-center text-[11px] leading-relaxed text-faint">
            {reportIsFast
              ? "快速模式不生成时序图，点上方「生成深度理解」即可补齐"
              : "本次索引没有产出时序图（可能没有满足条件的核心模块）"}
          </div>
        )}
      </section>
    </div>
  );
}

const moduleKey = (m: ModuleInfo) => `${m.kind}:${m.name}`;

/**
 * 模块子导图（M5 D1）：顶层导图只画到模块，文件层在这里按需展开。
 * mermaid 串由 lib/mermaid.ts 用已加载的模块地图数据本地拼装，点击不发请求。
 */
function ModuleMindmap({ modules }: { modules: ModuleInfo[] | null }) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const sorted = useMemo(() => {
    if (!modules) return [];
    const order = new Map<string, number>(
      MODULE_KIND_ORDER.map((k, i) => [k as string, i])
    );
    return [...modules].sort(
      (a, b) =>
        (order.get(a.kind) ?? 99) - (order.get(b.kind) ?? 99) ||
        (b.files?.length ?? 0) - (a.files?.length ?? 0) ||
        a.name.localeCompare(b.name, "zh")
    );
  }, [modules]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sorted;
    return sorted.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        (m.route_prefix ?? "").toLowerCase().includes(q)
    );
  }, [sorted, query]);

  const selected = useMemo(
    () => sorted.find((m) => moduleKey(m) === selectedKey) ?? null,
    [sorted, selectedKey]
  );
  const code = useMemo(
    () => (selected ? buildModuleMindmap(selected) : ""),
    [selected]
  );

  if (!modules) {
    return (
      <div className="border border-line bg-panel px-4 py-6 text-center text-[11px] tracking-wide text-faint">
        LOADING MODULES…
      </div>
    );
  }
  if (modules.length === 0) return null;

  return (
    <div className="border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-shade px-4 py-2.5">
        <div className="min-w-0">
          <div className="text-[12.5px] font-medium">模块子导图</div>
          <div className="text-[10px] tracking-wide text-dim">
            点击模块查看其文件结构 · 本地渲染，不产生后端请求
          </div>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="筛选模块…"
          aria-label="筛选模块"
          className="ml-auto w-[150px] border border-line bg-panel px-2 py-1 text-[11px] placeholder:text-faint"
        />
      </div>

      <div className="flex max-h-[152px] flex-wrap content-start gap-1.5 overflow-y-auto border-b border-hair p-3">
        {shown.length === 0 ? (
          <span className="px-1 py-2 text-[11px] text-faint">没有匹配的模块</span>
        ) : (
          shown.map((m) => {
            const key = moduleKey(m);
            const on = key === selectedKey;
            const meta = moduleKindMeta(m.kind);
            return (
              <button
                key={key}
                onClick={() => setSelectedKey(on ? null : key)}
                aria-pressed={on}
                title={`${meta.label} · ${m.files?.length ?? 0} 个文件`}
                className={`border px-2 py-1 text-[11px] ${
                  on
                    ? "border-accent bg-accent/[.08] text-accent"
                    : "border-line text-muted hover:border-ink hover:text-ink"
                }`}
              >
                {m.name}
                <span className={on ? "text-accent/70" : "text-faint"}>
                  {" "}
                  {m.files?.length ?? 0}
                </span>
              </button>
            );
          })
        )}
      </div>

      {selected ? (
        <div className="p-3">
          <MermaidDiagram
            title={selected.name}
            subtitle={[
              moduleKindMeta(selected.kind).label,
              selected.route_prefix,
              `${selected.files?.length ?? 0} 个文件`,
              (selected.files?.length ?? 0) > MODULE_MINDMAP_FILE_LIMIT
                ? `图中只画前 ${MODULE_MINDMAP_FILE_LIMIT} 个`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
            code={code}
          />
        </div>
      ) : (
        <div className="px-4 py-8 text-center text-[11px] text-faint">
          选择上方任一模块，展开它的文件子导图
        </div>
      )}
    </div>
  );
}

/** 页签二：功能地图（模块按 kind 分组，展开看文件与 L2 摘要）。 */
function ModulesTab({
  modules,
  error,
  structureMermaid,
  dataflowMermaid,
}: {
  modules: ModuleInfo[] | null;
  error: string;
  /** M6：结构导图（Project→Module）从项目理解页签移到这里，技术视角归技术页签。 */
  structureMermaid: string;
  /** M6：模块数据流图同理归入本页签。 */
  dataflowMermaid: string;
}) {
  if (error) return <ErrorCard message={error} />;
  if (!modules) return <Loading text="LOADING MODULES…" />;
  if (modules.length === 0) {
    return (
      <div className="border border-dashed border-line py-14 text-center text-[11px] text-faint">
        暂无模块数据，请先完成一次索引
      </div>
    );
  }

  const known = new Set<string>(MODULE_KIND_ORDER);
  const groups = MODULE_KIND_ORDER.map((kind) => ({
    kind: kind as string,
    list: modules.filter((m) => m.kind === kind),
  })).filter((g) => g.list.length > 0);
  const others = modules.filter((m) => !known.has(m.kind));
  if (others.length) groups.push({ kind: "other", list: others });

  return (
    <div className="flex flex-col gap-7">
      <section className="flex flex-col gap-2.5">
        <SectionLabel text="STRUCTURE 模块结构导图" />
        {structureMermaid.trim() ? (
          <MermaidDiagram
            title="模块结构导图"
            subtitle="由图谱中的 项目 → 模块 结构程序化生成"
            code={structureMermaid}
          />
        ) : (
          <div className="border border-dashed border-line py-10 text-center text-[11px] text-faint">
            尚无结构导图（重新索引后生成）
          </div>
        )}
        <ModuleMindmap modules={modules} />
      </section>

      {dataflowMermaid.trim() && (
        <section className="flex flex-col gap-2.5">
          <SectionLabel text="DATAFLOW 模块数据流图" />
          <MermaidDiagram
            title="模块数据流图"
            subtitle="模块间接口调用（实线）与跨模块引用（虚线）聚合，边标注为调用次数"
            code={dataflowMermaid}
          />
        </section>
      )}

      {groups.map((g) => {
        const meta = moduleKindMeta(g.kind);
        return (
          <section key={g.kind}>
            <div className="mb-2.5 flex flex-wrap items-center gap-2.5">
              <span className={`border px-2 py-[3px] text-[10px] tracking-wide ${meta.cls}`}>
                {meta.label}
              </span>
              <span className="text-[11px] text-muted">{meta.hint}</span>
              <span className="text-[10px] tracking-wide text-faint">
                {g.list.length} MODULES
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              {g.list.map((m) => (
                <ModuleCard key={`${m.kind}:${m.name}`} module={m} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function ModuleCard({ module: m }: { module: ModuleInfo }) {
  const [open, setOpen] = useState(false);
  const files = m.files ?? [];
  return (
    <div className="border border-line bg-panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-[13px] font-medium">{m.name}</div>
        {m.route_prefix && (
          <span className="border border-hair bg-shade px-1.5 py-0.5 text-[10px] text-ink2">
            {m.route_prefix}
          </span>
        )}
        <span className="ml-auto text-[10px] tracking-wide text-faint">
          {files.length} FILES
        </span>
      </div>

      <p className="mt-2 whitespace-pre-wrap text-[12px] leading-relaxed text-ink2">
        {m.summary?.trim() || "（暂无模块摘要）"}
      </p>

      {files.length > 0 && (
        <>
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="mt-3 text-[10px] tracking-wide text-muted hover:text-ink"
          >
            {open ? "▾" : "▸"} FILES（{files.length}）
          </button>
          {open && (
            <div className="mt-2.5 flex flex-col gap-2.5 border-t border-hair pt-2.5">
              {files.map((f) => (
                <div key={f.path}>
                  <div className="break-all text-[11px] text-ink">{f.path}</div>
                  <div className="mt-0.5 text-[11px] leading-relaxed text-muted">
                    {f.summary?.trim() || "（暂无文件摘要）"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** 页签三：索引记录（倒序任务表格，stats 可展开，失败显示错误）。 */
function JobsTab({ projectId, mock }: { projectId: string; mock: boolean }) {
  const [jobs, setJobs] = useState<IndexJob[] | null>(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    if (mock) {
      setJobs(MOCK_JOBS);
      return;
    }
    const load = async () => {
      try {
        const list = await api<IndexJob[]>(`/projects/${projectId}/jobs`);
        // 不依赖后端返回顺序，前端按开始时间倒序（spec 要求最新在前）
        const sorted = [...list].sort(
          (a, b) =>
            new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
        );
        if (!stopped) setJobs(sorted);
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    };
    load();
    const timer = setInterval(load, 4000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [projectId, mock]);

  if (error) return <ErrorCard message={error} />;
  if (!jobs) return <Loading text="LOADING JOBS…" />;
  if (jobs.length === 0) {
    return (
      <div className="border border-dashed border-line py-14 text-center text-[11px] text-faint">
        还没有索引任务
      </div>
    );
  }

  return (
    <div className="overflow-x-auto border border-line bg-panel">
      <table className="w-full min-w-[760px] text-[12px]">
        <thead className="border-b border-line bg-shade text-left text-[10px] tracking-label text-dim">
          <tr>
            <th className="px-4 py-2.5 font-normal">STARTED</th>
            <th className="px-4 py-2.5 font-normal">KIND</th>
            <th className="px-4 py-2.5 font-normal">STATUS</th>
            <th className="px-4 py-2.5 font-normal">STAGE</th>
            <th className="px-4 py-2.5 font-normal">PROGRESS</th>
            <th className="px-4 py-2.5 font-normal">DURATION</th>
            <th className="px-4 py-2.5 font-normal">STATS</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => {
            const badge = jobStatusBadge(j.status);
            const open = openId === j.id;
            const stats = Object.entries(j.stats_json ?? {});
            const partial = j.status === "succeeded" && !!j.error_text;
            return (
              <tr
                key={j.id}
                className={`border-b border-hair align-top last:border-b-0 ${
                  j.status === "failed" ? "bg-danger/[.03]" : ""
                }`}
              >
                <td className="px-4 py-3 text-muted">{formatDateTime(j.started_at)}</td>
                <td className="px-4 py-3 text-muted">{j.kind}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span
                      className={`border px-2 py-[3px] text-[10px] tracking-wide ${badge.cls}`}
                    >
                      {badge.label}
                    </span>
                    {partial && (
                      <span className="border border-line px-2 py-[3px] text-[10px] tracking-wide text-ink2">
                        PARTIAL 部分降级
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 text-muted">{stageLabel(j.stage)}</td>
                <td className="px-4 py-3 text-muted">{j.progress}%</td>
                <td className="px-4 py-3 text-muted">
                  {formatDuration(j.started_at, j.finished_at)}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => setOpenId(open ? null : j.id)}
                    aria-expanded={open}
                    className="text-[10px] tracking-wide text-muted hover:text-ink"
                  >
                    {open ? "▾ 收起" : "▸ 展开"}
                  </button>
                  {open && (
                    <div className="mt-2.5 flex w-[420px] max-w-full flex-col gap-2">
                      {stats.length > 0 ? (
                        <div className="grid grid-cols-2 gap-x-4 gap-y-1 border border-hair bg-shade p-3 text-[11px]">
                          {stats.map(([k, v]) => (
                            <div key={k} className="flex justify-between gap-2">
                              <span className="text-muted">{statLabel(k)}</span>
                              <span className="text-ink">{String(v)}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-[11px] text-faint">无统计数据</div>
                      )}
                      {j.error_text && (
                        <div
                          className={`whitespace-pre-wrap border-l-2 px-3 py-2 text-[11px] leading-relaxed ${
                            j.status === "failed"
                              ? "border-danger bg-danger/[.05] text-danger"
                              : "border-line bg-shade text-ink2"
                          }`}
                        >
                          {j.error_text}
                        </div>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
