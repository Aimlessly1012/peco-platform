/** 作品集首页占位（P5 会做成正式的作品卡片列表）。 */
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6">
      <div className="text-[11px] tracking-label text-dim">PECO / PORTFOLIO</div>
      <h1 className="mt-3 text-2xl font-semibold">作品集平台</h1>
      <p className="mt-4 text-[13px] leading-relaxed text-muted">
        骨架已就位。待建：GitHub 登录、审核准入、
        <span className="text-accent">/front</span> 组件库展示、
        <span className="text-accent">/rag</span> RAG Coder。
      </p>
    </main>
  );
}
