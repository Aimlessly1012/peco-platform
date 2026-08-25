"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";

/** 终端风顶栏：导航 + 当前用户。与 RAG 前端同一套令牌与结构。 */

interface NavItem {
  href: string;
  label: string;
  active: (p: string) => boolean;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { href: "/", label: "首页", active: (p) => p === "/" },
  { href: "/front", label: "组件库", active: (p) => p.startsWith("/front") },
  { href: "/rag", label: "RAG Coder", active: (p) => p.startsWith("/rag") },
  { href: "/admin", label: "审核", active: (p) => p.startsWith("/admin"), adminOnly: true },
];

export default function TopBar() {
  const pathname = usePathname() || "/";
  const { data: session, status } = useSession();
  const user = session?.user;
  const isAdmin = user?.role === "admin";
  const path = pathname === "/" ? "portfolio" : pathname.replace(/^\/+/, "");
  const items = NAV.filter((n) => !n.adminOnly || isAdmin);

  return (
    <header className="h-[52px] flex-none border-b border-line bg-panel">
      <div className="flex h-full items-center gap-5 px-6">
        <div className="flex items-center gap-[9px]">
          <span className="block h-[9px] w-[9px] bg-accent" />
          <Link href="/" className="text-sm font-semibold tracking-wide">
            PEKO
          </Link>
        </div>
        <span className="hidden truncate text-xs text-dim xl:block">peko://{path}</span>

        <nav className="flex items-center gap-4 text-[11px] tracking-wide">
          {items.map((n) => {
            const on = n.active(pathname);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={on ? "page" : undefined}
                className={`flex items-center gap-1.5 whitespace-nowrap ${
                  on ? "text-ink" : "text-muted hover:text-ink"
                }`}
              >
                <span className={`block h-[5px] w-[5px] ${on ? "bg-accent" : "bg-transparent"}`} />
                {n.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2.5 text-[11px]">
          {status === "loading" ? (
            <span className="text-faint">…</span>
          ) : user ? (
            <>
              <span className="max-w-[140px] truncate text-ink" title={user.name}>
                {user.name}
              </span>
              {isAdmin && (
                <span className="border border-accent/40 px-1.5 py-px text-[9px] tracking-wide text-accent">
                  ADMIN
                </span>
              )}
              {user.status !== "approved" && (
                <span className="border border-line px-1.5 py-px text-[9px] tracking-wide text-muted">
                  {user.status === "pending" ? "待审核" : "已拒绝"}
                </span>
              )}
              <button
                type="button"
                onClick={() => signOut({ callbackUrl: "/" })}
                className="border border-line px-2 py-1 text-[10px] tracking-wide text-muted hover:border-ink hover:text-ink"
              >
                登出
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => signIn("github")}
              className="border border-accent bg-accent/[.06] px-2.5 py-1 text-[10px] font-medium tracking-wide text-accent hover:bg-accent/[.12]"
            >
              GitHub 登录
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
