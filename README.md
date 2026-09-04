# peco-platform

个人作品集平台。一个前端、一次 GitHub 登录、统一终端风视觉。

```
/          作品集首页
/login     GitHub OAuth 登录
/pending   待审核（申请人登录后落这里）
/front     heitu 组件库展示
/rag/*     RAG Coder 页面（浏览器直连 /rag/api/* 取数，后端在 services/rag）
/admin     用户审核
```

## 架构要点

**单仓多项目，但运行时仍是两个服务**。M16 起 RAG Coder 后端并入 `services/rag/`
（FastAPI + LangGraph + Neo4j + tree-sitter，此前在独立仓库 RAG_coder）。
「同一个仓库」不等于「同一个进程」：

```
仓库根        app/ lib/ components/     Next.js 15 + TypeScript   npm / eslint / tsc
services/rag  app/ tests/ alembic/      FastAPI + LangGraph        uv / pytest / alembic
deploy/       docker-compose*.yml       两者的统一编排（项目名 peco）
```

两条工具链互不感知——`tsconfig.json` 与 eslint 都显式排除 `services/`，反之亦然。
CI 也按路径分成两个 workflow，各管各的。

**平台不做 API 代理层**。`/rag/*` 页面由浏览器直连 `/rag/api/*`（nginx 剥前缀转 FastAPI）：
那层代理要转发 SSE 流式与 MCP 长连接，风险大于收益。`lib/rag/api.ts` 只是类型定义加 fetch 封装，
不是服务端路由。

**数据库**与 RAG 后端共用同一个 Postgres：平台写 `platform_users`（GitHub 登录 upsert、审核状态），
后端只读校验。表名不叫 `users` 是因为 RAG 侧已有一张同名表。Neo4j 是 RAG 专用，平台不碰。

**登录态是跨服务契约**。NextAuth 改签 JWS(HS256)（不是默认的 JWE），后端用同一个密钥直接验签
同一个 cookie——签名可验、加密要解，只有 JWS 能让浏览器绕过平台直连后端。

**视觉统一靠设计令牌**：`tailwind.config.ts` 与 RAG 前端同源（paper/ink/accent、
IBM Plex Mono、无圆角）；`/front` 的 antd 组件经 ConfigProvider 适配同一套 token，
不用重写页面就能全站一致。

**版本刻意对齐 RAG 前端**（Next 15 + Tailwind v3，而非脚手架默认的 16 + v4）：
阶段二要迁十几个含 markmap / mermaid / SSE 的复杂页面，版本一致才没有摩擦。

## 开发

平台（仓库根）：

```bash
npm install
cp .env.local.example .env.local   # 按注释填写，GitHub OAuth 凭据要自己申请
npm run migrate                    # 建 platform_users 表（需要 Postgres 已启动）
npm run dev                        # :3000
```

RAG 后端（`services/rag/`，独立工具链）：

```bash
cd services/rag && uv sync --group dev
uv run pytest -m "not integration"   # 单测档，覆盖率门槛 78%
uv run pytest -m integration --no-cov  # 集成档，需 Neo4j
```

依赖服务（Postgres / Neo4j / RabbitMQ / MinIO）与全栈：

```bash
cd deploy && docker compose up -d    # 开发端口由 docker-compose.override.yml 叠加
```

`docker-compose.yml` 加 `compose/*.yml` 是**生产安全基线**：零宿主端口、零 restart。
开发端口只在默认发现时加载的 `docker-compose.override.yml` 里（db 5433、backend 9200、
neo4j 7474/7687、MinIO 9100/9101、RabbitMQ 5673）。方向不能反——compose 的 `ports` 是追加语义，
覆盖层删不掉基线里已有的映射，写反了就是把数据库挂到公网。

### 需要手动准备的东西

| 项 | 说明 |
|---|---|
| GitHub OAuth App | <https://github.com/settings/developers> 新建，回调填 `<站点地址>/api/auth/callback/github`，把 Client ID / Secret 写进 `.env.local` |
| `NEXTAUTH_SECRET` | `openssl rand -base64 32` 生成 |
| `ADMIN_GITHUB_ID` | 你的 GitHub **数字 id**（不是用户名）：`curl -s https://api.github.com/users/<用户名> \| grep '"id"'`。这个账号首次登录即 admin + approved，其余人一律 pending |
| Postgres | `deploy/` 那套 compose 起的库（开发端口 `localhost:5433`）；`npm run migrate` 会建 `platform_users` 表 |
| RAG 后端 | 代码在 `services/rag/`，`.env` 另起一份（见该目录的 `.env.example`）。页面直连同域 `/rag/api/*`（nginx 剥前缀转 FastAPI），本地后端在别的端口时用 `NEXT_PUBLIC_RAG_API_BASE` 覆盖 |

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
| 4 | 建 `deploy/compose/<key>.yml`，在 `deploy/docker-compose.yml` 的 `include` 加一行 | `check:middleware` 非零退出，并分别指出是缺文件还是缺 `include` 行 |
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

**第 4 步为什么也要守卫**：nginx 那边是 `include projects/*.conf` 通配的，丢个 conf 进去自动生效；
而 **compose 的 `include` 不支持通配符**，每个带后端的项目都得手工往列表里加一行——又一处
「手写 + 每个项目重复一次 + 漏了不报错」，和 matcher 同类。

表里「无机械检查」的三步只能靠人——守卫覆盖的是**登记类**的遗漏（目录在不在、matcher 全不全、
compose 建没建且登记没登记），覆盖不了配置内容对不对：nginx conf 里写错上游地址、
后端验签实现有 bug，机器都看不出来。这一栏的「无」只应随时间减少，不该增加。

设计文档见 `openspec/`：平台自身在 `changes/`，RAG 的规格在 `specs/`。
