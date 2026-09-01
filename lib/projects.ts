/**
 * 项目注册表——平台有哪些项目，这里是唯一事实源。
 *
 * 在此之前，「项目清单」散在三个地方各写一遍：TopBar 的 NAV、首页的 WORKS、
 * middleware 的判断分支。加一个项目要摸着 RAG 的脚印挨个改，而 matcher 里
 * 那个裸路径陷阱（`"/rag/:path*"` 匹配不到 `/rag`，commit 6eaef3d 踩过）
 * 会随每个新项目重复一次。现在清单只有一份，三处消费它。
 *
 * **注册表是数据不是框架**：一个类型化数组，没有动态加载、没有配置文件、
 * 没有注册中心。项目数预计 2~4，抽象到此为止。
 *
 * `middleware.ts` 的 `config.matcher` 是唯一不能从这里生成的东西——Next 要求它是
 * 静态字面量。所以受保护项目的两条 matcher 仍要手写，由 `npm run check:middleware`
 * 盯着别漏。见 scripts/check-middleware.mjs。
 */

/**
 * 访问级别。**管的是进入，不是可见性**——`approved` 项目的入口对所有登录用户可见，
 * 待审用户点进去由 middleware 送到 `/pending`：「看得见但进不去、并被告知原因」
 * 比「入口凭空消失」更有用，他能看到批准之后会得到什么。
 * 只有 `admin` 项目隐藏入口。
 */
export type ProjectAccess = "public" | "approved" | "admin";

/**
 * 首页作品集卡片的展示内容。可选——没有它的项目（如 `/admin` 审核台）
 * 是内部工具不是作品，不进作品集。
 *
 * 与 `label` 分开是因为两处的语境不同：TopBar 要短（「组件库」），
 * 作品集要全称（「heitu 组件库」）。
 */
export interface ProjectShowcase {
  /** 卡片标题，可与 TopBar 的 label 不同 */
  name: string;
  /** 卡片头部的标识串，与目录名无关，纯展示 */
  slug: string;
  tagline: string;
  body: string;
  stack: string[];
  highlights: string[];
  status: string;
}

export interface Project {
  /** 目录名 / 路由前缀，如 `rag` 对应 `app/rag/` 与 `/rag` */
  key: string;
  /** TopBar 导航上的短标签 */
  label: string;
  /** 路由前缀，恒为 `/${key}`，单独列出是为了消费方不必拼字符串 */
  route: string;
  access: ProjectAccess;
  /** 是否有独立后端（`services/<key>/`）。接入清单与运维编排据此判断 */
  backend: boolean;
  showcase?: ProjectShowcase;
}

export const PROJECTS: Project[] = [
  {
    key: "rag",
    label: "RAG Coder",
    route: "/rag",
    access: "approved",
    backend: true,
    showcase: {
      name: "RAG Coder",
      slug: "rag-coder",
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
    },
  },
  {
    key: "front",
    label: "组件库",
    route: "/front",
    access: "public",
    backend: false,
    showcase: {
      name: "heitu 组件库",
      slug: "heitu",
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
  },
  {
    // 审核台是内部工具，不写 showcase 就不会进作品集首页
    key: "admin",
    label: "审核",
    route: "/admin",
    access: "admin",
    backend: false,
  },
];

/** 需要登录才能进的项目——即 matcher 必须覆盖的那些。 */
export const protectedProjects = () => PROJECTS.filter((p) => p.access !== "public");

/** 命中某个路径属于哪个项目。`/rag` 与 `/rag/x` 都算，`/ragdoll` 不算。 */
export function projectOf(pathname: string): Project | undefined {
  return PROJECTS.find((p) => pathname === p.route || pathname.startsWith(`${p.route}/`));
}
