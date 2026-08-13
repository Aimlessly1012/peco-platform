"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "./AuthProvider";

/**
 * 终端顶栏的路径显示与导航。
 *
 * 设计稿把 `rag-coder://projects` 写死在 layout 里，但 layout 是 server component
 * （要 export metadata），拿不到当前路由。这里单独抽成 client 组件：路径跟随真实
 * pathname，同时挂上 M3 的 /mcp-guide 与 M8 的 /invites（仅 admin）入口。
 */

interface NavItem {
  href: string;
  label: string;
  active: (p: string) => boolean;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { href: "/", label: "项目", active: (p) => p === "/" || p.startsWith("/projects") },
  { href: "/mcp-guide", label: "MCP 接入", active: (p) => p.startsWith("/mcp-guide") },
  {
    href: "/invites",
    label: "邀请码",
    active: (p) => p.startsWith("/invites"),
    adminOnly: true,
  },
];

export default function TopNav() {
  const pathname = usePathname() || "/";
  const { isAdmin } = useAuth();
  const path = pathname === "/" ? "projects" : pathname.replace(/^\/+/, "");
  const items = NAV.filter((n) => !n.adminOnly || isAdmin);

  return (
    <>
      <span className="hidden truncate text-xs text-dim xl:block">
        rag-coder://{path}
      </span>
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
              <span
                className={`block h-[5px] w-[5px] ${on ? "bg-accent" : "bg-transparent"}`}
              />
              {n.label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
