"use client";

import { useState } from "react";
import { useAuth } from "./AuthProvider";

/** 顶栏右侧：当前用户 + 角色标记 + 登出。 */
export default function UserMenu() {
  const { user, logout } = useAuth();
  const [busy, setBusy] = useState(false);

  if (!user) return null;

  const onLogout = async () => {
    setBusy(true);
    try {
      await logout();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2.5 text-[11px]">
      <span className="flex items-center gap-1.5">
        <span className="block h-[5px] w-[5px] bg-accent" />
        <span className="max-w-[120px] truncate text-ink" title={user.username}>
          {user.username}
        </span>
      </span>
      {user.role === "admin" && (
        <span
          className="border border-accent/40 px-1.5 py-px text-[9px] tracking-wide text-accent"
          title="管理员"
        >
          ADMIN
        </span>
      )}
      <button
        type="button"
        onClick={onLogout}
        disabled={busy}
        className="border border-line px-2 py-1 text-[10px] tracking-wide text-muted hover:border-ink hover:text-ink disabled:opacity-40"
      >
        {busy ? "登出中…" : "登出"}
      </button>
    </div>
  );
}
