"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { AdminUser, authApi } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";

/**
 * 用户管理（仅 admin，M11）。
 *
 * 禁用而非删除：数据全留着，随时可恢复。两条自锁护栏（不能禁自己、不能禁最后一个
 * 启用的 admin）由后端把关并回 400，这里如实展示它的文案。
 */
export default function UsersPage() {
  const router = useRouter();
  const { isAdmin, status, user } = useAuth();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);

  // member 直接送回首页（后端还会再拦一道 403）
  useEffect(() => {
    if (status === "authenticated" && !isAdmin) router.replace("/");
  }, [status, isAdmin, router]);

  const load = useCallback(async () => {
    try {
      const list = await authApi.listUsers();
      setUsers(list);
      setError("");
    } catch (e) {
      setError((e as Error).message);
      setUsers([]);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin, load]);

  const toggle = async (u: AdminUser) => {
    const disabling = !u.disabled_at;
    if (
      disabling &&
      !confirm(
        `确认禁用「${u.username}」？\n\n该用户会立即被登出且无法再登录，已有的会话与提问记录保留，随时可以恢复。`
      )
    ) {
      return;
    }
    setPendingId(u.id);
    setError("");
    try {
      if (disabling) await authApi.disableUser(u.id);
      else await authApi.enableUser(u.id);
      await load();
    } catch (e) {
      // 护栏（禁自己 / 最后一个 admin）走这里，后端文案直接展示
      setError((e as Error).message);
    } finally {
      setPendingId(null);
    }
  };

  if (!isAdmin) return null;

  const total = users?.length ?? 0;
  const disabled = users?.filter((u) => u.disabled_at).length ?? 0;
  const active = total - disabled;

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左栏：统计 */}
      <aside className="hidden w-[212px] flex-none flex-col gap-7 overflow-y-auto border-r border-line bg-canvas px-5 py-6 md:flex">
        <div className="flex flex-col gap-1.5">
          <div className="text-[10px] tracking-label text-dim">ACTIVE USERS</div>
          <div className="text-[38px] font-semibold leading-none">
            {String(active).padStart(2, "0")}
          </div>
          <div className="text-[11px] text-muted">
            {disabled > 0 ? `另有 ${disabled} 个已禁用` : "没有被禁用的账号"}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-label text-dim">TOTAL</div>
          <div className="text-[11px] text-muted">{total} 个账号</div>
        </div>

        <div className="mt-auto text-[11px] leading-relaxed text-faint">
          禁用不删除数据
          <br />
          <span className="text-muted">会话与提问记录保留</span>
        </div>
      </aside>

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-7 py-6">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[22px] font-semibold">用户</h1>
          <span className="text-[11px] text-dim">
            $ users --list<span className="text-accent">_</span>
          </span>
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
            还没有用户
          </div>
        ) : (
          <div className="overflow-x-auto border border-line bg-panel">
            <table className="w-full min-w-[940px] text-[12px]">
              <thead className="border-b border-line bg-shade text-left text-[10px] tracking-label text-dim">
                <tr>
                  <th className="px-4 py-2.5 font-normal">USER</th>
                  <th className="px-4 py-2.5 font-normal">ROLE</th>
                  <th className="px-4 py-2.5 font-normal">REGISTERED</th>
                  <th className="px-4 py-2.5 font-normal">LAST LOGIN</th>
                  <th className="px-4 py-2.5 font-normal">INVITE</th>
                  <th className="px-4 py-2.5 font-normal">SESSIONS</th>
                  <th className="px-4 py-2.5 font-normal">ASKS</th>
                  <th className="px-4 py-2.5 font-normal">STATUS</th>
                  <th className="px-4 py-2.5 text-right font-normal">ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const off = !!u.disabled_at;
                  const isSelf = u.username === user?.username;
                  const busy = pendingId === u.id;
                  return (
                    <tr
                      key={u.id}
                      className={`border-b border-hair align-middle last:border-b-0 ${
                        off ? "bg-shade text-faint" : ""
                      }`}
                    >
                      <td className="px-4 py-3">
                        <span
                          className={`text-[12.5px] ${
                            off ? "text-muted" : "font-medium text-ink"
                          }`}
                        >
                          {u.username}
                        </span>
                        {isSelf && (
                          <span className="ml-1.5 text-[10px] tracking-wide text-faint">
                            （你）
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`border px-2 py-[3px] text-[10px] tracking-wide ${
                            off
                              ? "border-hair text-faint"
                              : u.role === "admin"
                                ? "border-accent/40 text-accent"
                                : "border-line text-muted"
                          }`}
                        >
                          {u.role === "admin" ? "ADMIN" : "MEMBER"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted">
                        {formatDateTime(u.created_at)}
                      </td>
                      <td className="px-4 py-3 text-muted">
                        {u.last_login_at ? formatDateTime(u.last_login_at) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        {u.invite_code ? (
                          <code className="text-[11px] text-ink2">{u.invite_code}</code>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted">{u.session_count}</td>
                      <td className="px-4 py-3 text-muted">{u.message_count}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`border px-2 py-[3px] text-[10px] tracking-wide ${
                            off ? "border-danger/40 text-danger" : "border-accent/40 text-accent"
                          }`}
                          title={
                            off && u.disabled_at
                              ? `禁用于 ${formatDateTime(u.disabled_at)}`
                              : undefined
                          }
                        >
                          {off ? "DISABLED 已禁用" : "ACTIVE 正常"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => toggle(u)}
                          disabled={busy}
                          title={
                            isSelf && !off
                              ? "不能禁用自己"
                              : off
                                ? "恢复该账号的登录权限"
                                : "禁用后该用户立即失效"
                          }
                          className={`border px-2.5 py-1 text-[10px] tracking-wide disabled:opacity-40 ${
                            off
                              ? "border-accent/40 text-accent hover:bg-accent/[.08]"
                              : "border-danger/40 text-danger hover:bg-danger/[.08]"
                          }`}
                        >
                          {busy ? "处理中…" : off ? "恢复" : "禁用"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
