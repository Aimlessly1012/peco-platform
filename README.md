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
cp .env.local.example .env.local   # 按注释填写，GitHub OAuth 凭据要自己申请
npm run migrate                    # 建 platform_users 表（需要 Postgres 已启动）
npm run dev
```

### 需要手动准备的东西

| 项 | 说明 |
|---|---|
| GitHub OAuth App | <https://github.com/settings/developers> 新建，回调填 `<站点地址>/api/auth/callback/github`，把 Client ID / Secret 写进 `.env.local` |
| `NEXTAUTH_SECRET` | `openssl rand -base64 32` 生成 |
| `ADMIN_GITHUB_ID` | 你的 GitHub **数字 id**（不是用户名）：`curl -s https://api.github.com/users/<用户名> \| grep '"id"'`。这个账号首次登录即 admin + approved，其余人一律 pending |
| Postgres | 复用 RAG 那套 compose 的库（默认 `localhost:5433`）；`npm run migrate` 会建 `platform_users` 表 |
| RAG 后端 | 页面直连同域 `/rag/api/*`（nginx 剥前缀转 FastAPI）。本地后端跑在别的端口时用 `NEXT_PUBLIC_RAG_API_BASE` 覆盖 |

### 路由与访问控制

| 路由 | 谁能进 |
|---|---|
| `/`、`/front`、`/login`、`/pending` | 公开 |
| `/admin` | 仅 admin（middleware + API 双重校验） |
| `/rag` | 项目列表 · 需登录且 `status=approved`、未禁用 |
| `/rag/projects/[id]` | 项目详情：项目理解 / 功能地图 / 索引记录 |
| `/rag/projects/[id]/chat` | 代码问答（SSE 流式 + `[n]` 引用联动） |
| `/rag/mcp` | MCP 接入说明 |

审核状态在 NextAuth 的 `jwt` 回调里**每次刷新都回库取最新值**——管理员批准或禁用后
立刻生效，不用等 token 过期，对方也不必重新登录。

设计文档见 RAG_coder 仓库的 `openspec/changes/m12-peco-platform/`。
