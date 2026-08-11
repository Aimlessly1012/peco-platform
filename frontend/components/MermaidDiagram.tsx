"use client";

import { useEffect, useId, useRef, useState } from "react";
import CopyButton from "./CopyButton";

/**
 * mermaid 渲染组件。
 *
 * 约定：
 * - mermaid 只在浏览器端通过动态 import 加载（模块顶层不 import，天然不参与 SSR）；
 * - render 全程 try/catch，失败时显示后端给的 fallback_text，没有则退回源码块，绝不白屏；
 * - 每张图右上角提供「复制源码」，源码即后端存的 mermaid 原文；
 * - 配色用 theme:"base" + themeVariables 对齐设计令牌，图不跳出终端风。
 */

type MermaidApi = typeof import("mermaid")["default"];

const MONO = '"IBM Plex Mono", "Noto Sans SC", ui-monospace, monospace';

/** 与 tailwind.config.ts 的设计令牌保持一致（mermaid 只吃字面色值）。 */
const THEME_VARIABLES = {
  background: "#ffffff",
  primaryColor: "#faf9f5",
  primaryTextColor: "#17171a",
  primaryBorderColor: "#d9d7cf",
  secondaryColor: "#efeee8",
  tertiaryColor: "#f5f4ef",
  lineColor: "#8a8880",
  textColor: "#17171a",
  fontFamily: MONO,
  fontSize: "13px",
  // sequenceDiagram
  actorBkg: "#faf9f5",
  actorBorder: "#0e7a45",
  actorTextColor: "#17171a",
  actorLineColor: "#d9d7cf",
  signalColor: "#4a4842",
  signalTextColor: "#4a4842",
  labelBoxBkgColor: "#efeee8",
  labelBoxBorderColor: "#d9d7cf",
  labelTextColor: "#17171a",
  loopTextColor: "#4a4842",
  noteBkgColor: "#f5f4ef",
  noteBorderColor: "#d9d7cf",
  noteTextColor: "#4a4842",
};

let mermaidPromise: Promise<MermaidApi> | null = null;

function loadMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => {
      const mermaid = mod.default;
      mermaid.initialize({
        startOnLoad: false,
        // LLM 产出的图文本按不可信内容处理，strict 会转义标签
        securityLevel: "strict",
        // 渲染失败时不要把 mermaid 自带的报错图塞进 DOM，由本组件兜底
        suppressErrorRendering: true,
        theme: "base",
        themeVariables: THEME_VARIABLES,
        fontFamily: MONO,
      });
      return mermaid;
    });
  }
  return mermaidPromise;
}

/** mermaid 的 parse error 是多行长文本，提示条里只留首行摘要。 */
function briefError(message: string): string {
  const first = message.split("\n").find((l) => l.trim()) ?? "";
  return first.length > 80 ? `${first.slice(0, 80)}…` : first;
}

type RenderState =
  | { kind: "loading" }
  | { kind: "ok"; svg: string }
  | { kind: "failed"; message: string };

export default function MermaidDiagram({
  code,
  fallbackText,
  title,
  subtitle,
}: {
  code: string;
  fallbackText?: string | null;
  title: string;
  subtitle?: string | null;
}) {
  const rawId = useId();
  // useId 含冒号/书名号，进到 mermaid 内部的 getElementById/querySelector 会炸，清洗成合法 id
  const baseId = `mermaid-${rawId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  // StrictMode 下 effect 跑两次，两次 render 撞同一个 DOM id，这里每次渲染再加序号
  const seq = useRef(0);
  const [state, setState] = useState<RenderState>({ kind: "loading" });
  const [showSource, setShowSource] = useState(false);
  const source = (code || "").trim();

  useEffect(() => {
    let cancelled = false;
    if (!source) {
      setState({ kind: "failed", message: "mermaid 源码为空" });
      return;
    }
    setState({ kind: "loading" });
    const renderId = `${baseId}-${seq.current++}`;

    (async () => {
      try {
        const mermaid = await loadMermaid();
        const { svg } = await mermaid.render(renderId, source);
        if (!cancelled) setState({ kind: "ok", svg });
      } catch (e) {
        if (!cancelled) {
          setState({
            kind: "failed",
            message: e instanceof Error ? e.message : String(e),
          });
        }
      } finally {
        // 渲染异常时 mermaid 可能残留临时节点，清掉避免污染页面
        if (typeof document !== "undefined") {
          document.getElementById(renderId)?.remove();
          document.getElementById(`d${renderId}`)?.remove();
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [source, baseId]);

  return (
    <div className="border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-shade px-4 py-2.5">
        <div className="min-w-0">
          <div className="truncate text-[12.5px] font-medium">{title}</div>
          {subtitle && (
            <div className="truncate text-[10px] tracking-wide text-dim">{subtitle}</div>
          )}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowSource((v) => !v)}
            className="border border-line px-2.5 py-1 text-[10px] tracking-wide text-muted hover:border-ink hover:text-ink"
          >
            {showSource ? "HIDE SRC" : "SRC"}
          </button>
          <CopyButton text={source} label="COPY SRC" />
        </div>
      </div>

      <div className="p-4">
        {state.kind === "loading" && (
          <div className="py-10 text-center text-[11px] tracking-wide text-faint">
            RENDERING…
          </div>
        )}

        {state.kind === "ok" && (
          <div
            className="overflow-x-auto [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full"
            dangerouslySetInnerHTML={{ __html: state.svg }}
          />
        )}

        {state.kind === "failed" && (
          <div>
            <div className="mb-2 border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-[11px] leading-relaxed text-danger">
              图形渲染失败（{briefError(state.message) || "未知原因"}），
              {fallbackText ? "以下为文字版调用链路" : "以下为 mermaid 源码"}
            </div>
            <pre className="overflow-x-auto whitespace-pre-wrap border border-line bg-shade p-3 text-[11px] leading-relaxed text-ink2">
              {fallbackText || source || "（无源码）"}
            </pre>
          </div>
        )}

        {showSource && (
          <pre className="mt-3 overflow-x-auto border border-line bg-shade p-3 text-[11px] leading-relaxed text-ink2">
            {source || "（无源码）"}
          </pre>
        )}
      </div>
    </div>
  );
}
