"use client";

import type { JobStage } from "@/lib/api";
import { STAGE_LABEL, STAGE_ORDER } from "@/lib/labels";

/**
 * 分段式阶段进度条（设计稿的样式，段数由 M1 的四阶段升为 M3 的六阶段）。
 * 列表页行内与详情页头部共用，段宽自适应，超窄时靠 truncate 保底。
 */
export default function StageBar({
  stage,
  progress,
}: {
  stage: string;
  progress: number;
}) {
  const current = STAGE_ORDER.indexOf(stage as JobStage);
  const pct = Math.max(0, Math.min(100, progress));

  return (
    <div className="flex flex-1 gap-0.5">
      {STAGE_ORDER.map((s, i) => {
        const text = STAGE_LABEL[s];
        if (current >= 0 && i < current) {
          return (
            <div
              key={s}
              className="flex h-[22px] flex-1 items-center justify-center overflow-hidden bg-accent px-1 text-[10px] tracking-wide text-paper"
            >
              <span className="truncate">{text} ✓</span>
            </div>
          );
        }
        if (i === current) {
          return (
            <div
              key={s}
              className="relative flex h-[22px] flex-[1.4] items-center justify-center overflow-hidden border border-accent/50 bg-panel px-1"
            >
              <div
                className="absolute inset-y-0 left-0 bg-accent/[.13]"
                style={{ width: `${pct}%` }}
              />
              <span className="relative truncate text-[10px] font-medium tracking-wide text-accent">
                {text} {pct}%
              </span>
            </div>
          );
        }
        return (
          <div
            key={s}
            className="flex h-[22px] flex-1 items-center justify-center overflow-hidden border border-line bg-paper px-1 text-[10px] tracking-wide text-faint"
          >
            <span className="truncate">{text}</span>
          </div>
        );
      })}
    </div>
  );
}
