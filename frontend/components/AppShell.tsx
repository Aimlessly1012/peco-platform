"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import TopNav from "./TopNav";
import UserMenu from "./UserMenu";
import { LOGIN_PATH } from "./AuthProvider";

/**
 * 应用外壳：终端顶栏 + 内容区。
 *
 * 抽成 client 组件是因为登录页要走整屏布局（没有顶栏），而 layout 是 server
 * component 拿不到 pathname。
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";

  if (pathname === LOGIN_PATH) {
    return <div className="flex h-screen flex-col overflow-hidden">{children}</div>;
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="h-[52px] flex-none border-b border-line bg-panel">
        <div className="flex h-full items-center gap-5 px-6">
          <div className="flex items-center gap-[9px]">
            <span className="block h-[9px] w-[9px] bg-accent" />
            <Link href="/" className="text-sm font-semibold tracking-wide">
              RAG&nbsp;CODER
            </Link>
          </div>
          <TopNav />
          <div className="ml-auto flex items-center gap-[22px]">
            <div className="hidden gap-[22px] text-[11px] text-muted lg:flex">
              <span>
                neo4j <span className="text-accent">●</span> up
              </span>
              <span>
                pg <span className="text-accent">●</span> up
              </span>
            </div>
            <UserMenu />
          </div>
        </div>
      </header>
      <main className="flex min-h-0 flex-1">{children}</main>
    </div>
  );
}
