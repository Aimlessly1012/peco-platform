"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { signOut, useSession } from "next-auth/react";

/** 待审核 / 被拒 / 被禁用的落地页。 */
export default function PendingPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const user = session?.user;

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
    // 已经批准的人不该停在这儿
    if (status === "authenticated" && user?.status === "approved" && !user.disabled) {
      router.replace("/");
    }
  }, [status, user, router]);

  const state = user?.disabled
    ? "disabled"
    : user?.status === "rejected"
      ? "rejected"
      : "pending";

  const COPY = {
    pending: {
      label: "PENDING 待审核",
      title: "申请已提交，等待管理员批准",
      body: "管理员批准后即刻生效——刷新本页或重新进入站点就能访问受保护页面，不需要重新登录。",
      cls: "border-line text-muted",
    },
    rejected: {
      label: "REJECTED 已拒绝",
      title: "这个账号的访问申请被拒绝了",
      body: "如果你认为这是误操作，请联系站点管理员复核。",
      cls: "border-danger/40 text-danger",
    },
    disabled: {
      label: "DISABLED 已禁用",
      title: "这个账号已被停用",
      body: "账号数据都还在，管理员恢复后即可继续使用。",
      cls: "border-danger/40 text-danger",
    },
  }[state];

  return (
    <div className="flex flex-1 items-center justify-center px-4">
      <div className="w-full max-w-[520px] border border-line bg-panel">
        <div className="flex items-center gap-2.5 border-b border-line bg-shade px-[18px] py-3">
          <span className="block h-2 w-2 bg-accent" />
          <span className="text-[10px] tracking-label text-dim">ACCOUNT STATUS</span>
        </div>
        <div className="flex flex-col gap-4 px-[26px] py-7">
          <span className={`w-fit border px-2 py-[3px] text-[10px] tracking-wide ${COPY.cls}`}>
            {COPY.label}
          </span>
          <div className="text-[15px] font-medium">{COPY.title}</div>
          <p className="text-[12px] leading-relaxed text-muted">{COPY.body}</p>

          {user && (
            <dl className="flex flex-col gap-1.5 border-t border-hair pt-4 text-[11px]">
              <div className="flex gap-3">
                <dt className="w-[80px] tracking-label text-dim">ACCOUNT</dt>
                <dd className="text-ink2">{user.name}</dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-[80px] tracking-label text-dim">GITHUB ID</dt>
                <dd className="text-ink2">{user.githubId}</dd>
              </div>
            </dl>
          )}

          <div className="mt-1 flex gap-2">
            <Link
              href="/"
              className="border border-line px-3 py-2 text-[11px] tracking-wide text-muted hover:border-ink hover:text-ink"
            >
              ← 回首页
            </Link>
            <button
              type="button"
              onClick={() => signOut({ callbackUrl: "/" })}
              className="border border-line px-3 py-2 text-[11px] tracking-wide text-muted hover:border-ink hover:text-ink"
            >
              登出
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
