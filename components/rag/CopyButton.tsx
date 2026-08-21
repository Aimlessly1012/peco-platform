"use client";

import { useEffect, useRef, useState } from "react";

/** 复制文本到剪贴板；非安全上下文下退回 execCommand。 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 继续走兜底 */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/** 终端风小按钮：无圆角、细边框，复制成功转 accent。 */
export default function CopyButton({
  text,
  label = "COPY",
  copiedLabel = "COPIED ✓",
  className = "",
}: {
  text: string;
  label?: string;
  copiedLabel?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );

  const onClick = async () => {
    const ok = await copyText(text);
    setState(ok ? "copied" : "failed");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 1800);
  };

  const tone =
    state === "copied"
      ? "border-accent text-accent"
      : state === "failed"
        ? "border-danger text-danger"
        : "border-line text-muted hover:border-ink hover:text-ink";

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label} 到剪贴板`}
      className={`border px-2.5 py-1 text-[10px] tracking-wide transition-colors ${tone} ${className}`}
    >
      {state === "copied" ? copiedLabel : state === "failed" ? "FAILED" : label}
    </button>
  );
}
