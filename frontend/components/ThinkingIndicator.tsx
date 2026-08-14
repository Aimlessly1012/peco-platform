"use client";

import { useEffect, useState } from "react";

/**
 * 首 token 之前的等待态（M8 F7）。
 *
 * 大项目实测首 token 要 25-30 秒（两次 LLM 前置调用 + 4096 维检索 + rerank），
 * 静止的「思考中」会让人以为挂了。这里给三样东西：动的光标、随时间推进的阶段
 * 文案、以及已等待秒数。阶段优先用后端 stage 事件（M9），拿不到才按计时推断。
 */

/**
 * 后端 stage 事件 → 文案（M9）。后端灰度期间可能一个 stage 都不发，
 * 所以计时兜底必须留着；未知 stage 一律忽略，保持当前文案不跳。
 */
const STAGE_LABEL: Record<string, string> = {
  rewrite: "正在理解问题",
  classify: "正在理解问题",
  rewrite_classify: "正在理解问题",
  retrieve: "正在检索相关代码",
  generate: "正在生成回答",
};

export function stageLabel(stage: string | null | undefined): string | null {
  if (!stage) return null;
  return STAGE_LABEL[stage] ?? null;
}

/** 没有 stage 事件时的兜底：按已等待秒数推断，说的是「在干什么」而非精确进度。 */
const PHASES: { at: number; label: string }[] = [
  { at: 0, label: "正在理解问题" },
  { at: 4, label: "正在检索相关代码" },
  { at: 12, label: "正在阅读命中的代码块" },
  { at: 22, label: "正在生成回答" },
];

const SLOW_HINT_AFTER = 20;

function phaseFor(elapsed: number): string {
  let label = PHASES[0].label;
  for (const p of PHASES) if (elapsed >= p.at) label = p.label;
  return label;
}

export default function ThinkingIndicator({
  startedAt,
  pinged = false,
  stage,
}: {
  /** 发起提问的时间戳（Date.now()）。 */
  startedAt: number;
  /** 是否已收到过 SSE 心跳——收到说明连接确实活着。 */
  pinged?: boolean;
  /** 后端 stage 事件；给了就以它为准，没给就退回计时推断。 */
  stage?: string | null;
}) {
  const [elapsed, setElapsed] = useState(() =>
    Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
  );

  useEffect(() => {
    const tick = () =>
      setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  return (
    <div
      className="flex items-start gap-3 border border-hair bg-panel px-5 py-[18px]"
      role="status"
      aria-live="polite"
    >
      {/* 闪烁块光标 */}
      <span className="mt-[3px] block h-[13px] w-[7px] animate-pulse bg-accent" />

      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex items-center gap-2 text-[13px] text-ink2">
          <span>{stageLabel(stage) ?? phaseFor(elapsed)}</span>
          <span className="flex items-center gap-[3px]" aria-hidden>
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="block h-[4px] w-[4px] animate-pulse bg-dim"
                style={{ animationDelay: `${i * 0.25}s` }}
              />
            ))}
          </span>
        </div>

        <div className="text-[10px] leading-relaxed tracking-wide text-faint">
          已等待 {elapsed}s
          {pinged && <span className="text-accent"> · 连接正常</span>}
          {elapsed >= SLOW_HINT_AFTER && (
            <span> · 大项目首次回答通常要 25-30 秒，请再等等</span>
          )}
        </div>
      </div>
    </div>
  );
}
