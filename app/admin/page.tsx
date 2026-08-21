"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import type { PlatformUser, UserAction } from "@/lib/users";

/** 用户审核页（仅 admin）。待审的排最前，带红点提醒。 */
export default function AdminPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const isAdmin = session?.user?.role === "admin";
  const [users, setUsers] = useState<PlatformUser[] | null>(null);
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
    if (status === "authenticated" && !isAdmin) router.replace("/");
  }, [status, isAdmin, router]);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/users");
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || `请求失败 (${res.status})`);
      setUsers(body as PlatformUser[]);
      setError("");
    } catch (e) {
      setError((e as Error).message);
      setUsers([]);
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    // setState 放进 async 回调而不是 effect 体内，避免级联渲染
    let alive = true;
    (async () => {
      try {
        const res = await fetch("/api/admin/users");
        const body = await res.json();
        if (!alive) return;
        if (!res.ok) throw new Error(body?.detail || `请求失败 (${res.status})`);
        setUsers(body as PlatformUser[]);
        setError("");
      } catch (e) {
        if (alive) {
          setError((e as Error).message);
          setUsers([]);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [isAdmin]);

  const act = async (u: PlatformUser, action: UserAction) => {
    const confirmText: Partial<Record<UserAction, string>> = {
      reject: `确认拒绝「${u.name}」的访问申请？`,
      disable: `确认禁用「${u.name}」？该账号会立即失去访问权限，数据保留，随时可恢复。`,
    };
    if (confirmText[action] && !confirm(confirmText[action])) return;

    setPendingId(u.id);
    setError("");
    try {
      const res = await fetch(`/api/admin/users/${u.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.detail || `操作失败 (${res.status})`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPendingId(null);
    }
  };

  if (status === "loading" || !isAdmin) {
    return (
      <div className="flex flex-1 items-center justify-center text-[11px] tracking-wide text-faint">
        {status === "loading" ? "CHECKING SESSION…" : "REDIRECTING…"}
      </div>
    );
  }

  const pending = users?.filter((u) => u.status === "pending") ?? [];
  const approved = users?.filter((u) => u.status === "approved" && !u.disabled_at) ?? [];

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-[212px] flex-none flex-col gap-7 overflow-y-auto border-r border-line bg-canvas px-5 py-6 md:flex">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[10px] tracking-label text-dim">PENDING</span>
            {pending.length > 0 && (
              <span className="block h-[6px] w-[6px] animate-pulse bg-danger" aria-label="有待审核申请" />
            )}
          </div>
          <div className="text-[38px] font-semibold leading-none">
            {String(pending.length).padStart(2, "0")}
          </div>
          <div className="text-[11px] text-muted">
            {pending.length > 0 ? "等待你处理" : "没有待审申请"}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-label text-dim">ACTIVE</div>
          <div className="text-[11px] text-muted">{approved.length} 个可用账号</div>
        </div>

        <div className="mt-auto text-[11px] leading-relaxed text-faint">
          批准后立即生效
          <br />
          <span className="text-muted">无需对方重新登录</span>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-7 py-6">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[22px] font-semibold">用户审核</h1>
          <span className="text-[11px] text-dim">
            $ users --review<span className="text-accent">_</span>
          </span>
          {pending.length > 0 && (
            <span className="border border-danger/40 bg-danger/[.06] px-2 py-[3px] text-[10px] tracking-wide text-danger">
              {pending.length} 个待审
            </span>
          )}
        </div>

        {error && (
          <div className="border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-xs leading-relaxed text-danger">
            {error}
          </div>
        )}

        {!users ? (
          <div className="border border-line bg-panel py-16 text-center text-[11px] tracking-wide text-faint">
            LOADING USERS…
          </div>
        ) : users.length === 0 ? (
          <div className="border border-dashed border-line py-16 text-center text-sm text-faint">
            还没有人登录过
          </div>
        ) : (
          <div className="overflow-x-auto border border-line bg-panel">
            <table className="w-full min-w-[860px] text-[12px]">
              <thead className="border-b border-line bg-shade text-left text-[10px] tracking-label text-dim">
                <tr>
                  <th className="px-4 py-2.5 font-normal">USER</th>
                  <th className="px-4 py-2.5 font-normal">GITHUB ID</th>
                  <th className="px-4 py-2.5 font-normal">ROLE</th>
                  <th className="px-4 py-2.5 font-normal">REGISTERED</th>
                  <th className="px-4 py-2.5 font-normal">LAST LOGIN</th>
                  <th className="px-4 py-2.5 font-normal">STATUS</th>
                  <th className="px-4 py-2.5 text-right font-normal">ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <UserRow
                    key={u.id}
                    user={u}
                    self={u.github_id === session?.user?.githubId}
                    busy={pendingId === u.id}
                    onAction={act}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function UserRow({
  user: u,
  self,
  busy,
  onAction,
}: {
  user: PlatformUser;
  self: boolean;
  busy: boolean;
  onAction: (u: PlatformUser, a: UserAction) => void;
}) {
  const off = !!u.disabled_at;
  const state = off ? "disabled" : u.status;
  const badge = {
    pending: { label: "PENDING 待审", cls: "border-danger/40 text-danger" },
    approved: { label: "APPROVED 已批准", cls: "border-accent/40 text-accent" },
    rejected: { label: "REJECTED 已拒绝", cls: "border-line text-muted" },
    disabled: { label: "DISABLED 已禁用", cls: "border-danger/40 text-danger" },
  }[state];

  const btn =
    "border px-2.5 py-1 text-[10px] tracking-wide disabled:opacity-40 whitespace-nowrap";

  return (
    <tr
      className={`border-b border-hair align-middle last:border-b-0 ${
        off || u.status === "rejected" ? "bg-shade" : ""
      } ${u.status === "pending" ? "bg-accent/[.03]" : ""}`}
    >
      <td className="px-4 py-3">
        <span className={`text-[12.5px] ${off ? "text-muted" : "font-medium text-ink"}`}>
          {u.name}
        </span>
        {self && <span className="ml-1.5 text-[10px] tracking-wide text-faint">（你）</span>}
      </td>
      <td className="px-4 py-3 text-muted">{u.github_id}</td>
      <td className="px-4 py-3">
        <span
          className={`border px-2 py-[3px] text-[10px] tracking-wide ${
            u.role === "admin" ? "border-accent/40 text-accent" : "border-line text-muted"
          }`}
        >
          {u.role === "admin" ? "ADMIN" : "MEMBER"}
        </span>
      </td>
      <td className="px-4 py-3 text-muted">{formatDateTime(u.created_at)}</td>
      <td className="px-4 py-3 text-muted">{formatDateTime(u.last_login_at)}</td>
      <td className="px-4 py-3">
        <span
          className={`border px-2 py-[3px] text-[10px] tracking-wide ${badge.cls}`}
          title={off && u.disabled_at ? `禁用于 ${formatDateTime(u.disabled_at)}` : undefined}
        >
          {badge.label}
        </span>
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-end gap-2">
          {self ? (
            <span className="text-[10px] text-faint">不能操作自己</span>
          ) : (
            <>
              {u.status !== "approved" && (
                <button
                  type="button"
                  onClick={() => onAction(u, "approve")}
                  disabled={busy}
                  className={`${btn} border-accent/40 text-accent hover:bg-accent/[.08]`}
                >
                  {busy ? "…" : "批准"}
                </button>
              )}
              {u.status === "pending" && (
                <button
                  type="button"
                  onClick={() => onAction(u, "reject")}
                  disabled={busy}
                  className={`${btn} border-line text-muted hover:border-ink hover:text-ink`}
                >
                  拒绝
                </button>
              )}
              {u.status === "approved" &&
                (off ? (
                  <button
                    type="button"
                    onClick={() => onAction(u, "enable")}
                    disabled={busy}
                    className={`${btn} border-accent/40 text-accent hover:bg-accent/[.08]`}
                  >
                    {busy ? "…" : "恢复"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => onAction(u, "disable")}
                    disabled={busy}
                    className={`${btn} border-danger/40 text-danger hover:bg-danger/[.08]`}
                  >
                    {busy ? "…" : "禁用"}
                  </button>
                ))}
            </>
          )}
        </div>
      </td>
    </tr>
  );
}
