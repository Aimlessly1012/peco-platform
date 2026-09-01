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

### /front 的字段说明

四个 tab 的字段表是脚本从 `node_modules/heitu` 的 `.d.ts` 提取生成的，不是手写的：

```bash
npm run gen:reference     # 重新生成产物
npm run check:reference   # 只读校验：产物是否最新 + 人写条目是否全部生效，退出码即结论
```

`app/front/reference/curation.ts` 由人写（展示哪些字段、以及源里没有 TSDoc 时的中文说明），
`generated.ts` 是脚本产物、**不要手改**。

**升级 heitu 之后必须重跑**——注意这个触发条件容易被漏掉：升级时没人会去碰 `curation.ts`，
但产物已经过期，页面上的说明仍停留在旧版本。`check:reference` 已接入 CI
（`.github/workflows/ci-platform.yml`），忘了重跑会在那里被拦下。

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

### 新增一个项目

项目清单的唯一事实源是 `lib/projects.ts`。新增一个项目 = **新增几个文件 + 两处登记**，
不改任何既有文件（注册表与 middleware 除外）。按序执行：

| # | 做什么 | 漏了会怎样 |
|---|---|---|
| 1 | 建页面目录 `app/<key>/` | `check:middleware` 报错——注册表登记了但目录不存在 |
| 2 | 建后端目录 `services/<key>/`（纯前端项目跳过） | 无机械检查 |
| 3 | 建 `deploy/nginx/projects/<key>.conf`，写该项目的 `location` | 无机械检查；路由 404 |
| 4 | 建 `deploy/compose/<key>.yml`，在 `deploy/docker-compose.yml` 的 `include` 加一行 | 无机械检查；服务起不来 |
| 5 | 在 `lib/projects.ts` 加一行（`key`/`label`/`route`/`access`/`backend`，作品集项目再加 `showcase`） | 导航与首页不出现该项目 |
| 6 | 非 public 项目：在 `middleware.ts` 的 `matcher` 加**两条**——`/<key>` 与 `/<key>/:path*` | `check:middleware` 非零退出并指明缺哪条 |
| 7 | 后端按 `project-onboarding` spec 验平台 JWS（HS256，claim `githubId`/`role`/`status`） | 无机械检查；接口裸奔 |

跑 `npm run check:middleware && npm run lint && npm run build` 收尾。

**第 6 步必须两条**：`"/x/:path*"` 匹配不到 `/x` 裸路径本身——只写后者会让 `/x` 未登录直接
放行，commit `6eaef3d` 实测踩过。matcher 无法从注册表生成（Next 要求它是静态字面量），
所以这一步只能手写，守卫的存在就是为了盯它。

**第 3 步的 conf 不要挂进 `/etc/nginx/conf.d/`**：nginx 默认 `include conf.d/*.conf` 会把
那里的文件当顶层配置加载进 http 块，而项目 conf 是 `location` 片段、只能在 server 块里，
挂错位置容器直接起不来。挂载点是 `/etc/nginx/projects/`，见 `docker-compose.server.yml`。

**后端路由别忘了 SSE 三件套**（若该项目有流式接口）：`proxy_buffering off`、
`proxy_cache off`、`proxy_set_header Connection ""`，外加放宽的 `proxy_read_timeout`。
缺任何一条，流式响应会被 nginx 缓冲成「一次性返回」，前端表现为一直转圈。

表里「无机械检查」的四步只能靠人——守卫覆盖的是**登记类**的遗漏（目录在不在、matcher 全不全），
覆盖不了配置内容对不对。

设计文档见 `openspec/`：平台自身在 `changes/`，RAG 的规格在 `specs/`。
