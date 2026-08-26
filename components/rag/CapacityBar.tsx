"use client";

import type { Capacity } from "@/lib/rag/api";

/**
 * 容量条（M14）：`SLOTS 2/8 · DISK 41G free`。
 *
 * 只做展示与提示，不拦请求——真正的拒绝在后端。接口没上线/取不到时整条隐藏
 * （调用方传 null 即可），页面其余部分照常。
 */

/** 剩余槽位少到这个数就标警示色 */
const LOW_SLOTS = 2;

export default function CapacityBar({ capacity }: { capacity: Capacity | null }) {
  if (!capacity) return null;

  const { projects_used, projects_limit, disk_free_gb, disk_total_gb, accepting, reason } =
    capacity;

  const remaining = Math.max(0, projects_limit - projects_used);
  const slotsTight = projects_limit > 0 && remaining <= LOW_SLOTS;
  const slotsTone = !accepting || remaining === 0
    ? "text-danger"
    : slotsTight
      ? "text-accent"
      : "text-ink2";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border border-line bg-shade px-3 py-2 text-[11px]">
      <span className="flex items-center gap-1.5">
        <span
          className={`block h-[6px] w-[6px] ${accepting ? "bg-accent" : "bg-danger"}`}
          aria-hidden
        />
        <span className="tracking-label text-dim">CAPACITY</span>
      </span>

      <span className="text-muted">
        SLOTS{" "}
        <span className={slotsTone}>
          {projects_used}/{projects_limit}
        </span>
        {slotsTight && accepting && (
          <span className="ml-1 text-faint">（剩 {remaining} 个）</span>
        )}
      </span>

      <span className="text-muted">
        DISK <span className="text-ink2">{disk_free_gb}G</span> free
        <span className="text-faint"> / {disk_total_gb}G</span>
      </span>

      {/* reason 是后端给的完整中文句子，直接原样展示 */}
      {!accepting && reason && (
        <span className="min-w-0 flex-1 border-l-2 border-danger bg-danger/[.06] px-2 py-1 leading-relaxed text-danger">
          {reason}
        </span>
      )}
    </div>
  );
}
