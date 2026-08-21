# peco-platform

个人作品集平台。一个前端、一次 GitHub 登录、统一终端风视觉。

```
/          作品集首页
/login     GitHub OAuth 登录
/pending   待审核（申请人登录后落这里）
/front     heitu 组件库展示
/rag/*     RAG Coder 页面（阶段二自 RAG_coder/frontend 迁入）
/admin     用户审核
```

## 架构要点

**后端不在本仓库**。RAG Coder 的后端（FastAPI + LangGraph + Neo4j + tree-sitter）
保持独立服务，本平台通过 `/rag/api/*` 调用它——那套 Python 生态无法也不必并进 Next.js。

**数据库**与 RAG 后端共用同一个 Postgres：平台写 users（GitHub 登录 upsert、审核状态），
后端只读校验。Neo4j 是 RAG 专用，平台不碰。

**视觉统一靠设计令牌**：`tailwind.config.ts` 与 RAG 前端同源（paper/ink/accent、
IBM Plex Mono、无圆角）；`/front` 的 antd 组件经 ConfigProvider 适配同一套 token，
不用重写页面就能全站一致。

**版本刻意对齐 RAG 前端**（Next 15 + Tailwind v3，而非脚手架默认的 16 + v4）：
阶段二要迁十几个含 markmap / mermaid / SSE 的复杂页面，版本一致才没有摩擦。

## 开发

```bash
npm install
npm run dev
```

设计文档见 RAG_coder 仓库的 `openspec/changes/m12-peco-platform/`。
