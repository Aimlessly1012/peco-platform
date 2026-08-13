import type { Metadata } from "next";
import AppShell from "@/components/AppShell";
import AuthProvider from "@/components/AuthProvider";
import "./fonts.css";
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
            终端三栏的意图是各区独立滚动，所以 AppShell 里锁死视口高，滚动交给各页面内部容器。 */}
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
