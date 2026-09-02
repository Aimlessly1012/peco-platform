# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 命令

```bash
npm run dev        # 开发服务器 :3000
npm run build      # 生产构建（output: "standalone"）
npm run lint       # ESLint（eslint.config.mjs，flat config）
npm run migrate    # 跑 migrations/*.sql，幂等，需 Postgres 先起来
npm run gen:reference  # 重新生成 /front 的字段说明（升级 heitu 后必须跑，见下）
npm run check:reference # 只读校验：产物是否最新 + 人写条目是否全部生效，退出码即结论
```

后端（`services/rag/`，Python）与全栈编排：

```bash
cd services/rag && uv sync --group dev        # 装依赖
cd services/rag && uv run pytest -m "not integration"   # 单测档（覆盖率门槛 78%）
cd services/rag && uv run pytest -m integration --no-cov # 集成档，需 Neo4j
cd deploy && docker compose up -d             # 开发全栈（默认发现会叠加 override.yml）
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml \
               -f deploy/docker-compose.server.yml up -d   # 生产
```

**平台侧（TypeScript）没有测试框架**——`package.json` 里没有 vitest / jest / playwright。
不要假设 `npm test` 存在；平台改动的验证只有 `npm run lint`、`npm run build` 和手工点页面。

**CI 按项目分 workflow，各管各的 paths**（GitHub 的 paths 过滤是 workflow 级不是 job 级）：

- `ci.yml`（`services/rag/**`）：pytest 双档——单测跟每次 push/PR，集成档在 main push
  或手动触发时自带 Neo4j + MinIO
- `ci-platform.yml`（平台侧路径）：lint + build + 两个守卫（`check:middleware` /
  `check:reference`）

注意区分：平台改动**会**触发 CI，但那里面跑的是构建与守卫，**不是测试**——平台侧至今
没有测试框架。新项目接入 CI 是加第三个 workflow 文件，不是编辑这两个。

## 边界：单仓多语言，但运行时仍是两个服务

M16 起 RAG Coder 后端并入本仓库的 `services/rag/`（此前在 `../RAG_coder`，已冻结归档）。
**「同一个仓库」不等于「同一个进程」**——这条分界没有因为合并而消失：

| | 平台 | RAG 后端 |
|---|---|---|
| 位置 | 仓库根（`app/` `lib/` `components/`） | `services/rag/` |
| 技术栈 | Next.js 15 + TypeScript | FastAPI + LangGraph + Neo4j + tree-sitter |
| 工具链 | npm / eslint / tsc | uv / pytest / alembic |

`/rag/*` 页面**由浏览器直连** `/rag/api/*`（nginx 剥前缀转 FastAPI），平台**不做 API 代理层**——
那层代理要转发 SSE 流式与 MCP 长连接，风险大于收益。所以：

- 遇到 `/rag/api/...` 的行为问题，代码在 `services/rag/app/`，不在 `app/`
- `lib/rag/api.ts` 只是类型定义 + fetch 封装，不是服务端路由
- Neo4j 只有后端碰，平台侧不碰

**两条工具链互不感知**：`tsconfig.json` 与 eslint 都显式排除了 `services/`（否则平台
`npm run build` 会被后端测试夹具里故意不完整的 `.tsx` 卡住、eslint 会去扫 `.venv` 里
338M 第三方 JS）；反过来 Python 侧也不读平台的任何配置。改一侧的构建配置前，
先确认没有把另一侧拖进扫描范围。

## 鉴权：JWS 是跨服务契约（最容易踩的地方）

NextAuth 默认签发 **JWE（加密）**，本项目改成了 **JWS（HS256 签名）**，实现在 `lib/jwt.ts`。

原因：RAG 的 FastAPI 用**同一个密钥**直接验签这个 cookie，浏览器才能绕过平台直连后端。
签名可验、加密要解——只有 JWS 做得到。

改动鉴权时必须守住三条：

1. **`lib/auth.ts` 的 `authOptions` 和 `middleware.ts` 的 `withAuth` 必须显式共用 `lib/jwt.ts` 的
   同一套 encode/decode。** `withAuth` 内部自带默认 JWE 解码，完全不知道 `authOptions` 的配置——
   漏传的症状是：登录成功、首页正常，唯独 `/rag`、`/admin` 把已登录用户当未登录踢回登录页。
   （已经踩过一次，见 commit `72af2c2`。）
2. **token 的 payload 是跨仓契约**：`githubId` / `role` / `status` 这几个 claim 名和 HS256 算法，
   FastAPI 那边硬编码依赖。改名或换算法要同步改 `services/rag` 的验签代码，否则两边静默失效。
   （合并后两边同仓，但**仍然是两次独立部署**——改了不同步照样静默失效。）
3. **middleware 的 matcher 要同时列裸路径和子路径**：`"/rag/:path*"` **匹配不到** `/rag` 本身。
   只写子路径的后果是未登录访问 `/rag` 直接放行——越权。（commit `6eaef3d`。）

### 三层访问控制

| 层 | 位置 | 能力 |
|---|---|---|
| middleware | `middleware.ts` | edge runtime，**不能查库**（pg 进不去），只读 token 判断，负责"别让人先看到页面再被弹走" |
| 页面 | server component 里调 `currentUser()` | `lib/guard.ts` |
| API route | `requireActiveUser()` / `requireAdmin()` | 抛 `HttpError(status, msg)`，catch 后转 `{ detail }` JSON |

三层都要有，middleware 只是体验层，不能当作唯一防线。

### 审核状态每次刷新回库取

`lib/auth.ts` 的 `jwt` 回调在**每次登录态刷新时都查一次库**取最新 `status`/`role`，不是只在登录时写进
token。这是审核制成立的前提：管理员批准/禁用后立刻生效，不用等 30 天 token 过期。

代价是每个带 token 的请求多一次主键查询（个人站规模可接受）。**DB 连不上时保守降级为
`status=pending, disabled=true`**（宁可让人重登，也不放行已禁用的人）——注意这条降级路径目前
**没有任何日志或告警**，DB 抖动的表现是"所有人突然被踢出"。

## 数据层

与 RAG 后端**共用同一个 Postgres**。平台写 `platform_users`，RAG 后端只读校验。

- 表名刻意叫 `platform_users` 而非 `users`：RAG 的 M8 已有一张 `users`（密码账号），阶段三才合并
- `lib/db.ts` 的连接池挂在 `globalThis`——Next 热重载会重复求值模块，不挂全局会连接耗尽
- **查库的 API route 必须 `export const dynamic = "force-dynamic"`**，否则构建期会去连数据库
- 迁移文件写成幂等（`CREATE TABLE IF NOT EXISTS`），`scripts/migrate.mjs` 无脑重跑
- `scripts/migrate.mjs` 没装 dotenv，自己手解析 `.env.local` 里的 `DATABASE_URL`

审核操作（`app/api/admin/users/[id]/route.ts`）有两条自锁护栏，动这块时不能拆：
**不能操作自己的账号**、**不能拒绝/禁用最后一个可用的管理员**。少一条就能把自己锁在系统外。

## RAG 前端的两条既有约定

**SSE 解析**（`lib/rag/api.ts` 的 `askStream`）踩过的坑都固化在代码里，改动时别回退：

- 收到的字节流必须把 `\r\n` 归一成 `\n`（sse-starlette 新版默认 CRLF），否则 `indexOf("\n\n")`
  永远匹配不到块边界，整场流零事件——症状是聊天页"一直思考中"
- `:` 开头的心跳注释行只跳过该行，**不能丢弃整个块**（心跳可能和真事件粘在同一块）
- 未知 `event:` 类型静默忽略，后端加新事件不能把整块当错误吞掉

**后端类型演进**：`lib/rag/api.ts` 里 M5/M6 新增的字段（`feature_map_markdown`、`page_map_markdown`、
`business_flows`、`dataflow_mermaid`、`index_depth`…）**一律声明为可选**，旧报告拿不到时前端隐藏
对应区块而不是报错。后端先上线、前端后跟得住，靠的就是这条。

## 构建与部署

- `next.config.ts` 的 `output: "standalone"` 是 Dockerfile 的前提，不能删
- **Dockerfile 构建期不传任何 build-arg**：所有敏感配置都在运行时读（没有 `NEXT_PUBLIC_*` 被编译进
  产物），所以构建不需要真实数据库和 OAuth 凭据
- 容器里**必须设 `HOSTNAME=0.0.0.0`**：Next standalone 用它决定监听地址，容器里默认是容器 ID，
  多网络时只绑其中一个网段，nginx 会 502
- 编排全部在 `deploy/`，仓库根**不再有 compose 文件**。M16 前平台是独立一栈、靠
  `external: true` 挂到 RAG 的网络上；现在同属一个 compose 项目（`name: peco`），
  网络由伞文件提供，平台可以直接 `depends_on: db`
- **基线不含任何宿主端口与 restart**：`deploy/docker-compose.yml` + `compose/*.yml` 本身
  即生产安全形态，开发端口在 `docker-compose.override.yml`（仅默认发现时加载），
  生产增量在 `docker-compose.prod.yml`。方向不能反过来——compose 的 ports 是**追加**
  语义，覆盖层删不掉基线里已有的映射，写反了就是把数据库挂到公网
- 四个数据卷写死 `name: rag_coder_*`。项目名已改叫 `peco`，不固定卷名的话 `up` 会创建
  一组新空卷，线上数据「看起来消失」——这个前缀是化石，不要顺手改整齐

## 视觉令牌

`tailwind.config.ts` 的色板（paper/ink/accent、IBM Plex Mono、无圆角）与 RAG 前端**同源**，
`/front` 的 antd 组件经 `components/AntdTerminalTheme.tsx` 的 ConfigProvider 适配同一套 token。
改配色要两边一起改，否则 `/rag/*` 和 `/front` 会视觉分裂。

Tailwind 的 `content` 必须包含 `./lib/**`——`lib/rag/labels.ts` 里也写类名。

**版本刻意锁在 Next 15 + Tailwind v3**（不是脚手架默认的 16 + v4），为的是和 RAG 前端一致，
阶段二迁那十几个含 markmap / mermaid / SSE 的页面才没有摩擦。升级前先确认 RAG 前端一起升。

React 19 需要 `@ant-design/v5-patch-for-react-19`，删了 antd 组件会报 hook 错误。

## /front 的字段说明

四个 tab 的字段表由 `npm run gen:reference` 生成，数据源是 `node_modules/heitu/dist/**/*.d.ts`
（不跨仓引用 `../heitu-platform`——容器构建时隔壁仓库不存在）。三个文件分工：

| 文件 | 谁写 |
|---|---|
| `app/front/reference/types.ts` | 类型契约 |
| `app/front/reference/curation.ts` | **人写**：展示哪些字段、以及源里没有 TSDoc 时的中文说明 |
| `app/front/reference/generated.ts` | **脚本生成，不要手改**（与 `app/fonts.css` 同一约定） |

**升级 heitu 后必须重跑**，不跑的话页面上的说明会停留在旧版本——**而这条约定目前仍然没有
自动强制**。脚本会在清单与实际 `.d.ts` 对不上时报错退出，但前提是有人执行它。

`npm run check:reference` 是只读版，一步给出结论（产物是否最新、人写条目是否全部生效），
退出码即结果。

这条命令已经挂进 CI 了（`ci-platform.yml`，随 platform-project-slots）——「升级 heitu
后忘了重跑」如今会在 push 后红给你看，不再只靠记性。本地重跑仍是第一现场，CI 是兜底。

两条改动时容易搞反的规则：

- **说明与签名是人写优先、源 TSDoc 兜底**，不是反过来。覆盖层里有条目即代表人做过判断，
  故优先；没写才自动取源文本。曾按「TSDoc 优先」实现过，结果是人工润色的说明被上游讲实现
  细节的注释盖掉
- **展示范围 = demo 里实际出现过的字段**。canvas 模块有 274 个成员，大半是 `calcRingD()`
  这类内部方法，全量提取会把它们倒进展示页。判据是声明位置不是名字：`Circle.path2D` 是
  内部缓存（不展示），`ICustom.path2D` 是必填构造参数（必须展示）

完整决策记录在 `openspec/changes/add-heitu-field-reference/`。

## 字体

`fonts/` 下 318 个 woff2 分片 + `app/fonts.css`（**脚本生成，不要手改**，改 `scripts/fetch-fonts.py`）。
刻意不放 `public/`、刻意不合并成大文件，原因见 `README-fonts.md`。

## 环境变量

见 `.env.local.example`——**注意这个文件当前被 `.gitignore` 第 34 行的 `.env*` 规则误伤，没有入库**，
只存在于本地工作区。克隆出来的副本里没有它（README 的 `cp .env.local.example .env.local` 会失败）。

必需项：`DATABASE_URL`、`NEXTAUTH_URL`、`NEXTAUTH_SECRET`、`GITHUB_ID`、`GITHUB_SECRET`、
`ADMIN_GITHUB_ID`（GitHub **数字 id**，不是用户名；该账号首次登录即 admin + approved，其余人一律
pending）。可选 `NEXT_PUBLIC_RAG_API_BASE`（本地后端在别的端口时覆盖默认的 `/rag/api`）。
