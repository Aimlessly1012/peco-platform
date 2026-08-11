"use client";

import { usePathname } from "next/navigation";

/**
 * 终端顶栏的路径显示与导航。
 *
 * 设计稿把 `rag-coder://projects` 写死在 layout 里，但 layout 是 server component
 * （要 export metadata），拿不到当前路由。这里单独抽成 client 组件：路径跟随真实
 * pathname，同时挂上 M3 的 /mcp-guide 入口。
 */

const NAV = [
  { href: "/", label: "项目", active: (p: string) => p === "/" || p.startsWith("/projects") },
  { href: "/mcp-guide", label: "MCP 接入", active: (p: string) => p.startsWith("/mcp-guide") },
];

export default function TopNav() {
  const pathname = usePathname() || "/";
  const path = pathname === "/" ? "projects" : pathname.replace(/^\/+/, "");

  return (
    <>
      <span className="hidden truncate text-xs text-dim sm:block">
        rag-coder://{path}
      </span>
      <nav className="flex items-center gap-4 text-[11px] tracking-wide">
        {NAV.map((n) => {
          const on = n.active(pathname);
          return (
            <a
              key={n.href}
              href={n.href}
              aria-current={on ? "page" : undefined}
              className={`flex items-center gap-1.5 ${
                on ? "text-ink" : "text-muted hover:text-ink"
              }`}
            >
              <span
                className={`block h-[5px] w-[5px] ${on ? "bg-accent" : "bg-transparent"}`}
              />
              {n.label}
            </a>
          );
        })}
      </nav>
    </>
  );
}
