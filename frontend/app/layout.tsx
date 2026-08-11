import type { Metadata } from "next";
import TopNav from "@/components/TopNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAG Coder",
  description: "代码 RAG 后台管理",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-paper text-ink antialiased">
        {/* 稿子用的是 min-h-screen：内容一长会整页滚动，左栏/SOURCES 常驻栏跟着跑掉。
            终端三栏的意图是各区独立滚动，所以这里锁死视口高，滚动交给各页面内部容器。 */}
        <div className="flex h-screen flex-col overflow-hidden">
          <header className="h-[52px] flex-none border-b border-line bg-panel">
            <div className="flex h-full items-center gap-5 px-6">
              <div className="flex items-center gap-[9px]">
                <span className="block h-[9px] w-[9px] bg-accent" />
                <a href="/" className="text-sm font-semibold tracking-wide">
                  RAG&nbsp;CODER
                </a>
              </div>
              <TopNav />
              <div className="ml-auto hidden gap-[22px] text-[11px] text-muted md:flex">
                <span>
                  neo4j <span className="text-accent">●</span> up
                </span>
                <span>
                  pg <span className="text-accent">●</span> up
                </span>
              </div>
            </div>
          </header>
          <main className="flex min-h-0 flex-1">{children}</main>
        </div>
      </body>
    </html>
  );
}
