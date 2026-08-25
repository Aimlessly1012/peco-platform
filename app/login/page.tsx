"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { signIn, useSession } from "next-auth/react";

/** GitHub 登录页。已登录的人直接按状态送去该去的地方。 */
function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session, status } = useSession();
  const error = params.get("error");
  const next = params.get("callbackUrl") || "/";

  useEffect(() => {
    if (status !== "authenticated") return;
    const u = session.user;
    if (u.status === "approved" && !u.disabled) router.replace(next);
    else router.replace("/pending");
  }, [status, session, next, router]);

  return (
    <div className="flex flex-1 items-center justify-center px-4">
      <div className="w-full max-w-[420px]">
        <div className="mb-6 flex items-center gap-[9px]">
          <span className="block h-[9px] w-[9px] bg-accent" />
          <span className="text-sm font-semibold tracking-wide">PEKO</span>
          <span className="text-[11px] text-dim">
            $ auth --github<span className="text-accent">_</span>
          </span>
        </div>

        <div className="border border-ink bg-panel shadow-[8px_8px_0_rgba(23,23,26,.07)]">
          <div className="flex items-center gap-2.5 border-b border-line bg-shade px-[18px] py-3">
            <span className="block h-2 w-2 bg-accent" />
            <span className="text-[10px] tracking-label text-dim">SIGN IN</span>
          </div>
          <div className="flex flex-col gap-4 px-[26px] py-7">
            <p className="text-[12px] leading-relaxed text-muted">
              用 GitHub 账号登录。首次登录会创建一条待审核记录，
              管理员批准后才能访问 RAG Coder 等受保护页面。
            </p>

            {error && (
              <div className="border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-[11px] leading-relaxed text-danger">
                登录失败（{error}）。如果是 OAuth 配置问题，检查 GITHUB_ID / GITHUB_SECRET
                与回调地址是否正确。
              </div>
            )}

            <button
              type="button"
              onClick={() => signIn("github", { callbackUrl: next })}
              disabled={status === "loading"}
              className="bg-ink px-4 py-[11px] text-[11px] font-medium tracking-wide text-paper disabled:opacity-50"
            >
              {status === "loading" ? "检查登录态…" : "使用 GitHub 登录"}
            </button>

            <p className="text-[10px] leading-relaxed text-faint">
              首页与组件库展示无需登录，可直接浏览。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  // useSearchParams 需要 Suspense 边界，否则静态预渲染会失败
  return (
    <Suspense fallback={<div className="flex flex-1 items-center justify-center text-[11px] text-faint">LOADING…</div>}>
      <LoginInner />
    </Suspense>
  );
}
