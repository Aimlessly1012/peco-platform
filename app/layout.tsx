import type { Metadata } from "next";
import Providers from "@/components/Providers";
import TopBar from "@/components/TopBar";
import "./fonts.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "peco — 作品集",
  description: "个人作品集平台：RAG Coder、heitu 组件库",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-paper text-ink antialiased">
        <Providers>
          {/* 各页面自己滚动，顶栏常驻——与 RAG 前端同一套壳 */}
          <div className="flex h-screen flex-col overflow-hidden">
            <TopBar />
            <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
