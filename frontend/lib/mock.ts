/**
 * 仅用于后端接口尚未就绪时的前端自测：详情页 URL 加 `?mock=1` 即用本文件的假数据渲染，
 * 不影响正常访问。后端联调通过后可整文件删除（只被 app/projects/[id]/page.tsx 引用）。
 */
import type { IndexJob, ModuleMap, UnderstandingReport } from "./api";

export function isMockMode(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("mock") === "1";
}

export const MOCK_REPORT: UnderstandingReport = {
  generated_at: new Date().toISOString(),
  depth: "deep",
  // 四层结构（产品 → 业务组 → 功能域 → 功能点）。想自测归组降级的三层形态，
  // 把下面的 "### xxx" 行删掉即可，前端会自动换成三层文案与展开行为。
  feature_map_markdown: [
    "# 示例电商后台：面向运营的订单与商品管理系统",
    "",
    "## 交易履约",
    "### 下单流程",
    "- 填写收货信息",
    "- 提交并创建订单",
    "- 查看下单结果",
    "### 订单管理",
    "- 按状态筛选订单",
    "- 查看订单详情",
    "- 流转订单状态",
    "",
    "## 商品运营",
    "### 商品资料",
    "- 维护商品资料",
    "- 编辑商品详情",
    "### 库存管理",
    "- 调整库存数量",
    "- 下单时扣减库存",
  ].join("\n"),
  page_map_markdown: [
    "# 示例电商后台 · 页面结构",
    "",
    "## /checkout 下单",
    "### /checkout 收货信息",
    "- 地址表单",
    "- 提交订单",
    "",
    "## /orders 订单",
    "### /orders 订单列表",
    "- 状态筛选",
    "- 分页浏览",
    "### /orders/:id 订单详情",
    "- 商品明细",
    "- 状态流转",
    "",
    "## /products 商品",
    "### /products 商品列表",
    "- 商品检索",
  ].join("\n"),
  business_flows: [
    {
      title: "用户下单流程",
      mermaid: [
        "flowchart TD",
        '  A["用户填写收货信息"] --> B{"库存是否充足"}',
        '  B -->|"充足"| C["创建订单"]',
        '  B -->|"不足"| D["提示缺货并返回"]',
        '  C --> E["扣减库存"]',
        '  E --> F["展示下单结果"]',
      ].join("\n"),
      fallback_text: "填写收货信息 → 校验库存 → 创建订单 → 扣减库存 → 返回订单号",
    },
    {
      // 演示 mermaid 为空时的文字版兜底
      title: "退款流程（文字版）",
      mermaid: "",
      fallback_text:
        "用户发起退款 → 运营审核 → 审核通过则原路退款并回补库存；驳回则通知用户并记录原因。",
    },
  ],
  dataflow_mermaid: [
    "flowchart LR",
    '  checkout["下单页 (page)"]',
    '  orders["订单模块 (api)"]',
    '  products["商品模块 (api)"]',
    '  shared["公共工具 (shared)"]',
    "  checkout -->|x6| orders",
    "  orders -->|x3| products",
    "  orders -.->|x4| shared",
    "  checkout -.->|x2| shared",
  ].join("\n"),
  doc_markdown: [
    "## 项目总览",
    "",
    "示例电商后台：前端 Next.js 负责下单与订单管理页面，后端 FastAPI 提供订单、商品、用户三组接口。",
    "",
    "## 订单模块（/api/orders）",
    "",
    "- **创建订单**：校验库存后写入 orders 表，返回订单号。",
    "- **订单查询**：按用户与状态分页查询。",
    "",
    "## 商品模块（/api/products）",
    "",
    "维护商品与库存，下单链路依赖其库存扣减接口。",
  ].join("\n"),
  mindmap_mermaid: [
    "mindmap",
    "  root((示例项目))",
    "    订单(orders · api · /api/orders)",
    "      api/orders/create.py",
    "      api/orders/query.py",
    "    商品(products · api · /api/products)",
    "      api/products/stock.py",
    "    下单页(checkout · page · /checkout)",
    "      app/checkout/page.tsx",
  ].join("\n"),
  sequences: [
    {
      module_key: "api:orders",
      module_name: "订单模块",
      mermaid: [
        "sequenceDiagram",
        "    participant U as 用户",
        "    participant P as 下单页 app/checkout/page.tsx",
        "    participant A as 订单接口 api/orders/create.py",
        "    participant S as 库存服务 api/products/stock.py",
        "    U->>P: 提交订单",
        "    P->>A: POST /api/orders",
        "    A->>S: 扣减库存",
        "    S-->>A: 扣减结果",
        "    A-->>P: 订单号",
      ].join("\n"),
      fallback_text: null,
    },
    {
      module_key: "api:products",
      module_name: "商品模块（演示渲染失败兜底）",
      mermaid: "sequenceDiagram\n    这不是合法的 mermaid 语法 %%%",
      fallback_text:
        "下单页 → POST /api/products/stock → 库存服务 stock.py:12-48 → products 表",
    },
  ],
};

export const MOCK_MODULES: ModuleMap = {
  modules: [
    {
      name: "下单页",
      kind: "page",
      route_prefix: "/checkout",
      summary: "下单主流程页面，收集收货信息并调用订单创建接口。",
      files: [
        { path: "app/checkout/page.tsx", summary: "下单页组件，表单校验后提交订单。" },
        { path: "app/checkout/hooks.ts", summary: "下单页数据获取与提交 hook。" },
        // 故意留一条含括号/方括号/引号的路径，用来验证子导图的 mermaid 转义
        {
          path: 'app/(dashboard)/[id]/"quoted"/page.tsx',
          summary: "路由组 + 动态段的页面，检验子导图节点转义。",
        },
      ],
    },
    {
      name: "订单模块",
      kind: "api",
      route_prefix: "/api/orders",
      summary: "订单创建、查询与状态流转接口。",
      files: [
        { path: "api/orders/create.py", summary: "创建订单：校验库存、写库、返回订单号。" },
        { path: "api/orders/query.py", summary: "按用户与状态分页查询订单。" },
      ],
    },
    {
      name: "公共工具",
      kind: "shared",
      route_prefix: null,
      summary: "跨模块复用的鉴权、日志与序列化工具。",
      files: [{ path: "lib/auth.py", summary: "JWT 解析与权限校验。" }],
    },
  ],
};

export const MOCK_JOBS: IndexJob[] = [
  {
    id: "mock-job-1",
    project_id: "mock",
    kind: "full",
    status: "succeeded",
    stage: "report",
    progress: 100,
    stats_json: {
      files_parsed: 128,
      files_skipped: 12,
      chunks: 964,
      modules: 9,
      api_edges: 23,
      sequences_ok: 5,
      sequences_fallback: 1,
    },
    error_text: null,
    started_at: new Date(Date.now() - 600_000).toISOString(),
    finished_at: new Date(Date.now() - 120_000).toISOString(),
  },
  {
    id: "mock-job-2",
    project_id: "mock",
    kind: "full",
    status: "failed",
    stage: "clone",
    progress: 5,
    stats_json: {},
    error_text: "克隆失败：认证被拒绝（请检查访问 Token）",
    started_at: new Date(Date.now() - 86_400_000).toISOString(),
    finished_at: new Date(Date.now() - 86_390_000).toISOString(),
  },
];
