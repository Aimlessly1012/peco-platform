"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import CopyButton from "./CopyButton";

/**
 * 需求功能思维导图（M6）：markmap 渲染 markdown 层级文本，XMind 式横向逻辑图。
 *
 * 约定：
 * - markmap 体积大且强依赖浏览器 API，只在 effect 里动态 import（模块顶层不 import，天然不参与 SSR）；
 * - transform / create 全程 try/catch，失败回退成 markdown 文本渲染，绝不白屏；
 * - 初始只展开根的直接子级，其余逐层点开；工具条可展开全部 / 收起 / 适应窗口 / 复制源码；
 * - 复制的是后端给的原始 markdown（不是从渲染树反推），可直接粘进 XMind。
 */

type MarkmapCtor = typeof import("markmap-view").Markmap;
type MarkmapInstance = InstanceType<MarkmapCtor>;
/** markmap 的纯数据树（transform 产物 / setData 入参），从 setData 签名推导，避免额外依赖 markmap-common。 */
type PureNode = NonNullable<Parameters<MarkmapInstance["setData"]>[0]>;

interface MarkmapApi {
  transform: (markdown: string) => PureNode;
  Markmap: MarkmapCtor;
}

let apiPromise: Promise<MarkmapApi> | null = null;

function loadMarkmap(): Promise<MarkmapApi> {
  if (!apiPromise) {
    apiPromise = Promise.all([
      // no-plugins 入口：默认入口会打进 katex / prism 等插件，它们的资源指向 CDN，
      // 而本项目静态资源全部自托管；功能导图只有三层纯文本，也用不到这些插件。
      import("markmap-lib/no-plugins"),
      import("markmap-view"),
    ]).then(
      ([lib, view]) => {
        const transformer = new lib.Transformer([]);
        return {
          transform: (markdown: string) =>
            transformer.transform(markdown).root as PureNode,
          Markmap: view.Markmap,
        };
      }
    );
  }
  return apiPromise;
}

/**
 * markmap 的 initialExpandLevel 语义是「折叠 depth ≥ N 的节点」，depth 从 1 起算。
 * 所以 2 = 只展开根的直接子级，剩下的逐层点开；-1 = 全展开。
 *
 * 实测（三层与四层产物都验过）：
 * - 四层 `# 产品 / ## 业务组 / ### 功能域 / - 功能点` → 停在业务组层
 * - 三层 `# 产品 / ## 功能域 / - 功能点`（归组降级）→ 停在功能域层
 * 两种结构用同一个值就对，不必按 `###` 探测层数。
 */
const EXPAND_DEFAULT = 2;
const EXPAND_ALL = -1;

/** 收敛到终端风设计令牌，与 tailwind.config.ts 的色值保持一致。 */
const INK = "#17171a";
const ACCENT = "#0e7a45";
const MUTED = "#6f6d66";

const MARKMAP_CSS_VARS = {
  "--markmap-font":
    '500 13px/1.5 "IBM Plex Mono", "Noto Sans SC", ui-monospace, monospace',
  "--markmap-text-color": INK,
  "--markmap-circle-open-bg": "#ffffff",
  "--markmap-a-color": ACCENT,
  "--markmap-a-hover-color": ACCENT,
  "--markmap-code-bg": "#faf9f5",
  "--markmap-code-color": "#4a4842",
  "--markmap-max-width": "320px",
} as React.CSSProperties;

type ViewState = "loading" | "ok" | "failed";

export default function MarkmapView({
  markdown,
  title,
  subtitle,
  height = 520,
  initialExpandLevel = EXPAND_DEFAULT,
}: {
  markdown: string;
  title: string;
  subtitle?: string | null;
  height?: number;
  /** 初始展开层级，语义见 EXPAND_DEFAULT 注释；「收起」按钮也回到这一层。 */
  initialExpandLevel?: number;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const mmRef = useRef<MarkmapInstance | null>(null);
  const rootRef = useRef<PureNode | null>(null);
  const roRef = useRef<ResizeObserver | null>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [state, setState] = useState<ViewState>("loading");
  const [message, setMessage] = useState("");
  const source = (markdown || "").trim();

  useEffect(() => {
    let cancelled = false;
    if (!source) {
      setState("failed");
      setMessage("功能导图内容为空");
      return;
    }
    setState("loading");

    (async () => {
      try {
        const { transform, Markmap } = await loadMarkmap();
        if (cancelled || !svgRef.current) return;
        const root = transform(source);
        rootRef.current = root;
        const mm = Markmap.create(
          svgRef.current,
          {
            initialExpandLevel,
            duration: 200,
            maxWidth: 320,
            spacingVertical: 8,
            spacingHorizontal: 90,
            paddingX: 12,
            // 层级配色：根 → 第二层 → 更深层，越浅越重
            color: (node) =>
              node.state.depth <= 1 ? INK : node.state.depth === 2 ? ACCENT : MUTED,
            lineWidth: (node) => (node.state.depth <= 1 ? 2 : 1),
          },
          // create 会在传入对象上挂 state 等字段，给它副本，原始树留作后续重设
          structuredClone(root)
        );
        mmRef.current = mm;
        if (!cancelled) setState("ok");
        // 初始 fit 的时机没有可靠信号：setData/renderData 的 promise 依赖 d3
        // transition end，实测可能永不 resolve；rAF 又早于内容 bbox 就绪。
        // fit 幂等且无副作用，直接在渲染动画（duration 200ms）后定时补两次
        const timers = [
          setTimeout(() => mm.fit().catch(() => {}), 400),
          setTimeout(() => mm.fit().catch(() => {}), 1200),
        ];
        timersRef.current = timers;
        // 窗口/容器尺寸变化时自动重新适配（observe 会立即触发一次，正好兜底）
        if (svgRef.current && typeof ResizeObserver !== "undefined") {
          const ro = new ResizeObserver(() => {
            mm.fit().catch(() => {});
          });
          ro.observe(svgRef.current);
          roRef.current = ro;
        }
      } catch (e) {
        if (!cancelled) {
          setMessage(e instanceof Error ? e.message : String(e));
          setState("failed");
        }
      }
    })();

    return () => {
      cancelled = true;
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      roRef.current?.disconnect();
      roRef.current = null;
      try {
        mmRef.current?.destroy();
      } catch {
        /* 卸载期报错无所谓 */
      }
      mmRef.current = null;
      // destroy 不清空宿主 svg，留着会和下一次 create 的内容叠在一起
      if (svgRef.current) svgRef.current.innerHTML = "";
    };
  }, [source, initialExpandLevel]);

  /** 重设展开层级：markmap 会变异传入的树，所以每次都给一份新副本。 */
  const applyExpand = useCallback((level: number) => {
    const mm = mmRef.current;
    const root = rootRef.current;
    if (!mm || !root) return;
    mm.setData(structuredClone(root), { initialExpandLevel: level })
      .then(() => mm.fit())
      .catch(() => {
        /* 交互失败不影响已渲染内容 */
      });
  }, []);

  const fit = useCallback(() => {
    mmRef.current?.fit().catch(() => {});
  }, []);

  const toolButton =
    "border border-line px-2.5 py-1 text-[10px] tracking-wide text-muted hover:border-ink hover:text-ink disabled:opacity-40";

  return (
    <div className="border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-shade px-4 py-2.5">
        <div className="min-w-0">
          <div className="truncate text-[12.5px] font-medium">{title}</div>
          {subtitle && (
            <div className="truncate text-[10px] tracking-wide text-dim">{subtitle}</div>
          )}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => applyExpand(EXPAND_ALL)}
            disabled={state !== "ok"}
            className={toolButton}
          >
            展开全部
          </button>
          <button
            type="button"
            onClick={() => applyExpand(initialExpandLevel)}
            disabled={state !== "ok"}
            className={toolButton}
          >
            收起
          </button>
          <button
            type="button"
            onClick={fit}
            disabled={state !== "ok"}
            className={toolButton}
          >
            适应窗口
          </button>
          <CopyButton text={source} label="COPY MD" />
        </div>
      </div>

      <div className="p-4">
        {state === "failed" ? (
          <div>
            <div className="mb-2 border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-[11px] leading-relaxed text-danger">
              功能导图渲染失败（{message || "未知原因"}），以下为 markdown 原文
            </div>
            <div className="prose prose-sm max-w-none prose-headings:font-semibold prose-p:my-0 prose-p:mb-2 prose-li:my-0.5 prose-code:bg-accent/[.08] prose-code:px-1 prose-code:text-accent prose-code:before:content-none prose-code:after:content-none">
              <ReactMarkdown>{source || "（无内容）"}</ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="relative">
            {state === "loading" && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-panel text-[11px] tracking-wide text-faint">
                RENDERING…
              </div>
            )}
            <svg
              ref={svgRef}
              role="img"
              aria-label={title}
              style={{ ...MARKMAP_CSS_VARS, height }}
              className="w-full"
            />
          </div>
        )}
      </div>

      {state === "ok" && (
        <div className="border-t border-hair px-4 py-2 text-[10px] leading-relaxed text-faint">
          点击节点圆点可展开 / 收起该分支 · 滚轮缩放、拖拽平移 · 「COPY MD」复制的 markdown
          可直接粘贴进 XMind
        </div>
      )}
    </div>
  );
}
