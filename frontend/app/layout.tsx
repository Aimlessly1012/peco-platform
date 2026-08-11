import type { Metadata } from "next";
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
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased">
        <header className="border-b bg-white">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
            <a href="/" className="text-lg font-semibold">
              RAG Coder
            </a>
            <span className="text-sm text-zinc-500">代码 RAG 后台管理</span>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
