import Link from "next/link";

/**
 * 作品集首页（M12 P5）——整个站的门面。
 * 公开可访问：访客不用登录就能看作品，登录只是为了进受保护的 RAG Coder。
 */

interface Work {
  slug: string;
  href: string;
  name: string;
  tagline: string;
  body: string;
  stack: string[];
  highlights: string[];
  status: string;
  /** 需要登录+审核才能进 */
  gated?: boolean;
  external?: string;
}

const WORKS: Work[] = [
  {
    slug: "rag-coder",
    href: "/rag",
    name: "RAG Coder",
    tagline: "代码库检索增强问答",
    body:
      "把一个陌生仓库变成能问答的知识库：克隆、解析分块、生成摘要、向量化、写入图谱，" +
      "最后产出需求功能导图、业务流程图与模块数据流图。聊天带出处，答案里的每个引用都能点回代码。",
    stack: ["Next.js", "FastAPI", "LangGraph", "Neo4j", "pgvector", "MCP"],
    highlights: [
      "六阶段索引管道，进度经 SSE 实时推送",
      "报告四件套：功能导图 / 页面结构 / 业务流程 / 时序图",
      "7 个 MCP 工具，可直接接进 Claude Code",
    ],
    status: "在线运行",
    gated: true,
  },
  {
    slug: "heitu",
    href: "/front",
    name: "heitu 组件库",
    tagline: "React 工具库 · hooks / 表单渲染 / canvas 图表",
    body:
      "自研的 React 工具库，已发布到 npm。JSON 配置驱动的表单渲染器支持联动、异步数据源与自定义控件；" +
      "图表基于 canvas 自绘，不依赖重型图表库。",
    stack: ["React", "TypeScript", "antd", "Canvas", "father"],
    highlights: [
      "FormRender：配置即表单，支持 watch 联动与 service 异步选项",
      "charts：折线 / 柱状 / 饼图 / 柱线混合，canvas 自绘",
      "hooks 与 canvas engine 独立入口，按需引入",
    ],
    status: "npm 已发布",
  },
];

export default function HomePage() {
  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-10 px-7 py-12">
      <section className="flex flex-col gap-3">
        <h1 className="text-[30px] font-semibold leading-none">peko</h1>
      </section>

      <section className="flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <span className="block h-[9px] w-[9px] bg-accent" />
          <span className="text-[10px] tracking-label text-dim">WORKS · {WORKS.length}</span>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {WORKS.map((w) => (
            <article
              key={w.slug}
              className="flex flex-col border border-line bg-panel transition-shadow hover:shadow-[6px_6px_0_rgba(23,23,26,.06)]"
            >
              <div className="flex items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
                <span className="block h-2 w-2 bg-accent" />
                <span className="text-[10px] tracking-label text-dim">
                  {w.slug.toUpperCase()}
                </span>
                <span className="ml-auto border border-line px-2 py-[2px] text-[9px] tracking-wide text-muted">
                  {w.status}
                </span>
              </div>

              <div className="flex flex-1 flex-col gap-4 p-5">
                <div className="flex flex-col gap-1">
                  <h2 className="text-[19px] font-semibold">{w.name}</h2>
                  <div className="text-[11px] tracking-wide text-accent">{w.tagline}</div>
                </div>

                <p className="text-[12px] leading-relaxed text-ink2">{w.body}</p>

                <ul className="flex flex-col gap-1.5 text-[11px] leading-relaxed text-muted">
                  {w.highlights.map((h) => (
                    <li key={h} className="flex gap-2">
                      <span className="mt-[6px] block h-[3px] w-[3px] flex-none bg-accent" />
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>

                <div className="flex flex-wrap gap-1.5">
                  {w.stack.map((s) => (
                    <span
                      key={s}
                      className="border border-hair bg-shade px-1.5 py-[2px] text-[10px] text-ink2"
                    >
                      {s}
                    </span>
                  ))}
                </div>

                <div className="mt-auto flex items-center gap-2 pt-1">
                  <Link
                    href={w.href}
                    className="bg-ink px-4 py-2 text-[11px] font-medium tracking-wide text-paper"
                  >
                    进入 →
                  </Link>
                  {w.gated && (
                    <span className="text-[10px] leading-relaxed text-faint">
                      需 GitHub 登录并通过审核
                    </span>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

    </div>
  );
}
