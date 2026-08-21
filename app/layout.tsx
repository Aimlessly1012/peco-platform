import type { Metadata } from "next";
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
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
