"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import CopyButton from "@/components/CopyButton";
import { authApi, InviteCode } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";

/** 邀请码管理（仅 admin）。后端同样有 require_admin，这里只是不给 member 看入口。 */
export default function InvitesPage() {
  const router = useRouter();
  const { isAdmin, status } = useAuth();
  const [invites, setInvites] = useState<InviteCode[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [justCreated, setJustCreated] = useState<string | null>(null);

  // member 直接送回首页（后端还会再拦一道 403）
  useEffect(() => {
    if (status === "authenticated" && !isAdmin) router.replace("/");
  }, [status, isAdmin, router]);

  const load = useCallback(async () => {
    try {
      const list = await authApi.listInvites();
      setInvites(list);
      setError("");
    } catch (e) {
      setError((e as Error).message);
      setInvites([]);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin, load]);

  const create = async () => {
    setCreating(true);
    setError("");
    try {
      const made = await authApi.createInvite();
      setJustCreated(made.code);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  if (!isAdmin) return null;

  const unused = invites?.filter((i) => !i.used_at).length ?? 0;
  const used = (invites?.length ?? 0) - unused;

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左栏：统计与操作 */}
      <aside className="hidden w-[212px] flex-none flex-col gap-7 overflow-y-auto border-r border-line bg-canvas px-5 py-6 md:flex">
        <div className="flex flex-col gap-1.5">
          <div className="text-[10px] tracking-label text-dim">UNUSED</div>
          <div className="text-[38px] font-semibold leading-none">
            {String(unused).padStart(2, "0")}
          </div>
          <div className="text-[11px] text-muted">已使用 {used} 枚</div>
        </div>

        <button
          onClick={create}
          disabled={creating}
          className="border border-accent bg-accent/[.06] px-3 py-2 text-[11px] font-medium tracking-wide text-accent hover:bg-accent/[.12] disabled:opacity-40"
        >
          {creating ? "生成中…" : "+ 生成邀请码"}
        </button>

        <div className="mt-auto text-[11px] leading-relaxed text-faint">
          邀请码一次性使用
          <br />
          <span className="text-muted">注册后自动作废</span>
        </div>
      </aside>

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-7 py-6">
        <div className="flex items-end justify-between gap-3">
          <div className="flex items-baseline gap-3">
            <h1 className="text-[22px] font-semibold">邀请码</h1>
            <span className="text-[11px] text-dim">
              $ invites --list<span className="text-accent">_</span>
            </span>
          </div>
          <button
            onClick={create}
            disabled={creating}
            className="border border-accent bg-accent/[.06] px-4 py-2 text-xs font-medium tracking-wide text-accent hover:bg-accent/[.12] disabled:opacity-40 md:hidden"
          >
            {creating ? "生成中…" : "+ 生成"}
          </button>
        </div>

        {error && (
          <div className="border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}

        {justCreated && (
          <div className="flex flex-wrap items-center gap-3 border border-accent/40 bg-accent/[.06] px-4 py-3">
            <span className="text-[10px] tracking-label text-dim">NEW</span>
            <code className="text-[13px] font-medium text-ink">{justCreated}</code>
            <CopyButton text={justCreated} label="COPY" className="ml-auto" />
          </div>
        )}

        {!invites ? (
          <div className="border border-line bg-panel py-16 text-center text-[11px] tracking-wide text-faint">
            LOADING INVITES…
          </div>
        ) : invites.length === 0 ? (
          <div className="border border-dashed border-line py-16 text-center text-sm text-faint">
            还没有邀请码，点「生成邀请码」发一枚
          </div>
        ) : (
          <div className="overflow-x-auto border border-line bg-panel">
            <table className="w-full min-w-[640px] text-[12px]">
              <thead className="border-b border-line bg-shade text-left text-[10px] tracking-label text-dim">
                <tr>
                  <th className="px-4 py-2.5 font-normal">CODE</th>
                  <th className="px-4 py-2.5 font-normal">STATUS</th>
                  <th className="px-4 py-2.5 font-normal">USED BY</th>
                  <th className="px-4 py-2.5 font-normal">CREATED</th>
                  <th className="px-4 py-2.5 font-normal">USED AT</th>
                </tr>
              </thead>
              <tbody>
                {invites.map((i) => {
                  const isUsed = !!i.used_at;
                  return (
                    <tr
                      key={i.code}
                      className={`border-b border-hair align-middle last:border-b-0 ${
                        isUsed ? "" : "bg-accent/[.03]"
                      }`}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <code
                            className={`text-[12.5px] ${
                              isUsed ? "text-muted line-through" : "font-medium text-ink"
                            }`}
                          >
                            {i.code}
                          </code>
                          {!isUsed && <CopyButton text={i.code} label="COPY" />}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`border px-2 py-[3px] text-[10px] tracking-wide ${
                            isUsed
                              ? "border-line text-muted"
                              : "border-accent/40 text-accent"
                          }`}
                        >
                          {isUsed ? "USED 已使用" : "OPEN 未使用"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted">{i.used_by_name || "—"}</td>
                      <td className="px-4 py-3 text-muted">
                        {formatDateTime(i.created_at)}
                      </td>
                      <td className="px-4 py-3 text-muted">
                        {i.used_at ? formatDateTime(i.used_at) : "—"}
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
