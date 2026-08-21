# M12 设计

## D1 仓库与部署形态

```
peco-platform/（新仓库）           RAG_coder/（现仓库，转纯后端）
  app/                              backend/
    page.tsx        作品集首页        ├── FastAPI + LangGraph
    login/          GitHub 登录       ├── Postgres（与平台共用）
    pending/        待审核             └── Neo4j（RAG 专用）
    front/          组件库展示        deploy/
    rag/            RAG 页面（迁入）   （frontend/ 迁出后删除）
    admin/          用户审核
    api/auth/       NextAuth
  lib/heitu/        组件库（git 依赖）
```

服务器容器编排（nginx 路由）：

```
/          → platform:3000        新平台（Next.js）
/rag/api/  → backend:8000         RAG 后端（剥前缀，SSE 三件套照旧）
/api/auth/ → platform:3000        NextAuth（平台自己处理）
```

`/rag` 不再单独转发到一个前端容器——它已是平台内部路由。RAG 前端容器下线。

## D2 认证：平台签发，后端验证

NextAuth 用 **JWT strategy + GitHub Provider**，`jwt` 回调每次查库取最新 status
（沿用 x-blog 的做法：管理员审批后立即生效，与 M11 给 RAG 做禁用时同一个思路）。

**FastAPI 怎么验证**：平台的服务端在转发到 `/rag/api/*` 时，用共享密钥签一个短时效
的内部 JWT（含 github_id、role、status），后端用同一密钥验签。

选它而不是"后端调平台 session 接口"的理由：
- 无运行时依赖（平台重启不影响已发出的请求）
- 无额外网络往返
- 密钥是我们自己定的对称密钥，不碰 NextAuth 的 JWE 加密细节（那才是脆弱的耦合）

浏览器直连 `/rag/api/*` 的路径（比如 SSE 与 MCP）需要平台侧的 route handler 代理，
或由 nginx 注入——**这是本设计最需要在实施时验证的一点**，SSE 流式与 MCP 长连接
都要确保代理不破坏（M6 踩过缓冲的坑、M7 踩过 root_path 的坑）。

## D3 用户模型统一

Postgres 里一张 users 表，平台与后端共用：

```
users: id | github_id(unique) | name | avatar_url | role(admin|member)
     | status(pending|approved|rejected) | disabled_at | last_login_at | created_at
```

- 平台写入（GitHub 登录时 upsert）、审核状态变更
- 后端只读（验证 status=approved 且 disabled_at 为空）
- M11 的用户管理页迁进 `/admin`，禁用逻辑保留
- **删除**：password_hash 字段、invite_codes 表（M8 产物）

`chat_sessions.user_id` 外键不变，历史会话按 user_id 保留。

## D4 视觉统一（终端风令牌）

一套令牌两处消费：

```
tokens: paper/ink/accent/line/muted、IBM Plex Mono、radius=0、间距阶梯
   ├→ Tailwind config（平台页面与迁入的 RAG 页面）
   └→ antd ConfigProvider theme.token（/front 的组件库 demo）
```

RAG 页面迁移时**不改结构与交互**，只确保令牌来源统一。markmap / mermaid 的内部配色
本来就是从令牌读的（M6 做的），跟着变即可。

## D5 迁移与切换

分三步，每步可独立验证、可回滚：

1. **平台骨架上线**：首页 + 登录 + pending + admin，部署到根路径（此时 `/rag` 仍走
   旧前端容器，两者共存互不影响）
2. **RAG 页面迁入**：页面搬进 `/rag/*`，后端加内部 JWT 验证（同时保留密码登录作为
   迁移期退路），验证通过后一次性切 nginx，下线旧前端容器
3. **清理**：删除 M8 的密码登录/邀请码代码与数据表、RAG_coder 的 frontend 目录

## D6 验收口径

- 平台：GitHub 登录 → pending 页 → admin 批准 → 可访问 `/rag`；未批准/被禁用访问
  `/rag/*` 一律挡下
- RAG 功能回归：项目录入、索引进度 SSE、报告各图渲染、聊天流式与 `[n]` 引用联动、
  MCP token 接入（MCP 走独立 token，不受账号体系影响）
- 视觉：`/front` 与 `/rag` 在同一套令牌下无明显割裂
