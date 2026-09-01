"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";
import { PROJECTS } from "@/lib/projects";

/** 终端风顶栏：导航 + 当前用户。与 RAG 前端同一套令牌与结构。 */

interface NavItem {
  href: string;
  label: string;
  active: (p: string) => boolean;
  adminOnly?: boolean;
}

/**
 * 导航由两截拼成：平台壳条目（首页）写死，项目条目来自注册表。
 *
 * 首页不是项目——它是壳，`active` 判据也特殊（`p === "/"`，不能按前缀匹配，
 * 否则任何路径都会命中）。项目条目的 active 统一由 route 推导。
 *
 * `access` 管进入不管可见性：approved 项目对所有登录用户可见，点进去由
 * middleware 送到 /pending；只有 admin 项目对非管理员隐藏。
 */
const NAV: NavItem[] = [
  { href: "/", label: "首页", active: (p) => p === "/" },
  ...PROJECTS.map((project) => ({
    href: project.route,
    label: project.label,
    active: (p: string) => p === project.route || p.startsWith(`${project.route}/`),
    adminOnly: project.access === "admin",
  })),
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
