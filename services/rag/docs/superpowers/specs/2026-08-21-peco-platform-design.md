# 个人作品集平台（peco-platform）设计

> 2026-08-21 · 由 RAG Coder 演进为多作品统一平台

## 背景

RAG Coder 已在服务器上稳定运行（`http://43.167.170.20/rag`），但它只是一个孤立的工具站。
现在要把它变成**个人作品集平台的一部分**：根路径是作品集门面，各个作品挂在子路径下，
共用一套登录与视觉。

同时解决一个现存问题：RAG Coder 的准入靠邀请码（M8），发出去就管不住，也没有"申请"入口。
新平台改用 GitHub 登录 + 审核制——任何人可以登录，但要等批准才能用。

原本还计划把申请推送到微信，**本期不做**（只在后台显示待审核提醒），接口留口子。

## 目标与非目标

**目标**
- 一个仓库、一次部署，装下平台首页、组件库展示、RAG Coder
- 一套登录（GitHub OAuth）、一套视觉（终端风）
- 申请审核制取代邀请码

**非目标（本期明确不做）**
- 微信/邮件等外部通知（后台红点足够）
- 把 Python 后端重写成 Node（FastAPI + LangGraph + Neo4j 是核心资产）
- 保留 x-blog 的博客与早报功能（用户已明确弃用）
- 迁移 x-blog 的 SQLite 数据（只借鉴其审核流程概念）

## 架构

```
新仓库 peco-platform
├── backend/                FastAPI（从 RAG_coder 搬迁）
│   ├── GitHub OAuth 登录    ← 替换 M8 的密码校验
│   ├── 用户审核 status       ← pending / approved / rejected
│   ├── RAG 全部能力          ← 索引管道 / 图谱 / 报告 / 聊天 / MCP
│   └── Postgres + Neo4j
└── frontend/               Next.js 15（终端风统一）
    ├── /                   作品集首页
    ├── /login              GitHub 登录入口
    ├── /pending            等待审核页
    ├── /front              heitu 组件库展示
    ├── /admin              用户审核与管理（由 M11 的 /users 页演化）
    └── /rag/*              RAG Coder 页面（从 RAG_coder 搬迁）
```

**为什么后端不合并进 Next.js**：索引管道依赖 tree-sitter 解析、LangGraph 工作流、Neo4j
图谱查询，全是 Python 生态。重写代价极大且毫无收益。前后端分离是正常架构。

**为什么登录放后端而不用 NextAuth**：后端已有完整的 JWT + httpOnly cookie 鉴权（M8）
与守卫依赖（M11 的查库校验）。让 FastAPI 统管认证，前端所有路由天然共享同一个 cookie，
不需要打通两套体系。这是本设计相对早期方案最大的简化。

## 认证与审核流程

```
访客 → /login 点「用 GitHub 登录」
     → 后端 302 到 GitHub 授权页
     → GitHub 回调 /auth/github/callback?code=...
     → 后端换取 access_token，拉取用户信息（id / login / avatar）
     → users 表 upsert：首次登录 status=pending
     → 签发 JWT cookie（与 M8 相同机制）
     → 前端根据 status 路由：pending → /pending，approved → 原目标页

管理员 → /admin（由 M11 的 /users 页演化而来：已有列表与禁用，加 status 列与批准按钮）
     → 看到待审核列表（红点提示数量）
     → 点批准 → status=approved
     → 申请人刷新即可用（守卫每次查库，即时生效——沿用 M11 的做法）
```

**首个管理员**：环境变量 `ADMIN_GITHUB_ID` 指定的 GitHub 用户 ID，首次登录直接
`status=approved` + `role=admin`。其余人一律 pending。

**被拒绝/禁用**：沿用 M11 的 `disabled_at`。status=rejected 与 disabled 都视为不可用，
落到 /pending 页并说明原因。

## 数据模型变更

`users` 表在 M8/M11 基础上调整：

| 字段 | 变更 | 说明 |
|---|---|---|
| `github_id` | 新增，唯一 | GitHub 用户 ID，认证主键 |
| `avatar_url` | 新增 | 头像，前端展示 |
| `status` | 新增 | pending / approved / rejected，默认 pending |
| `password_hash` | **删除** | 不再有密码登录 |
| `username` | 保留 | 存 GitHub login |
| `role` / `disabled_at` / `last_login_at` | 保留 | M8/M11 的机制原样有效 |

`invite_codes` 表**整表删除**——审核制取代邀请码。

其余表（projects / index_jobs / understanding_reports / chat_sessions / chat_messages）
完全不变。Neo4j 不受影响。

## 从 RAG_coder 搬迁的范围

**原样搬（不改）**
- 后端：索引管道、图谱读写、检索、报告生成、QA 工作流、MCP 服务、所有相关测试
- 前端：项目列表、项目详情（三页签含 markmap/mermaid）、聊天页、MCP 说明页、
  用户管理页、所有终端风组件与设计令牌

**要改**
- 后端 `api/auth.py`：删密码登录/注册/邀请码，改 GitHub OAuth（`authlib`）
- 后端 `services/auth/`：security 去掉 bcrypt，保留 JWT；deps 守卫加 status 校验
- 前端 `app/login/`：双 tab 表单 → 一个 GitHub 登录按钮
- 前端删 `app/invites/`（邀请码页作废）
- 前端 `app/users/` → `app/admin/`：它是平台级功能，不属于 `/rag` 命名空间
- 前端所有路由加 `/rag` 前缀（原本靠 basePath，现在变成真实路由段）

**新增**
- 前端 `/`：作品集首页
- 前端 `/front`：heitu 组件库展示（antd 通过 ConfigProvider 配终端风 token）
- 前端 `/pending`：等待审核页
- 后端：`/auth/users` 响应加 `status` 字段，新增 `POST /auth/users/{id}/approve` 与 `/reject`
  （沿用 M11 的 disable/enable 形态与两条防自锁护栏）

## 视觉统一策略

全站终端风：等宽字体（IBM Plex Mono）、无圆角、纸墨配色、绿色点缀。

**不重写页面**：RAG 页面本就是终端风，直接搬。heitu 组件库依赖的 antd 通过
`ConfigProvider` 的 theme token 适配同一套色板与圆角（`borderRadius: 0`、
`colorPrimary` 取 accent 绿、`fontFamily` 取等宽）。两边共用一份令牌定义。

## 部署

单个 `docker-compose.yml`：backend / frontend / postgres / neo4j / nginx 五个服务。
nginx 根路径直接给 frontend（不再需要 `/rag` basePath 重定向那套）。

**服务器切换**：新仓库 = 新容器名，与现有 `rag_coder-*` 容器可并存于同一台机器
（端口错开），验证通过后再停旧的。现有数据无需迁移——线上只剩一个诊断用测试项目。

## 风险与注意事项

1. **GitHub OAuth 回调地址要固定**。当前只有 IP（`http://43.167.170.20/auth/github/callback`）。
   以后加域名必须回 GitHub OAuth App 后台改一次，否则登录直接失败。建议在动手前
   先决定是否上域名。
2. **现有 5 个测试账号作废**（用户已确认接受）。他们重新用 GitHub 登录即可，
   但需要管理员再批准一次。
3. **`ADMIN_GITHUB_ID` 配错会把自己锁在外面**——所有人都是 pending 且无人能批准。
   首次部署必须先确认这个值（GitHub 用户 ID 是数字，不是用户名）。
4. **路由前缀改造**：RAG 前端原先靠 `basePath=/rag` 整体偏移，新平台里 `/rag` 是真实
   路由段。所有内部跳转与 API 调用路径需要核对一遍。
5. M6-M11 的 openspec 记录留在 RAG_coder 仓库，新仓库从头开始——历史决策的来龙去脉
   会断开，建议把关键的几条（模型分工、SSE 三件套、路由探测器设计）在新仓库 README
   里留个索引。

## 实施分期建议

| 期 | 内容 | 可验证成果 |
|---|---|---|
| 一 | 新仓库骨架 + 代码搬迁 + 本地跑通（登录仍用密码） | 现有功能在新仓库完整可用 |
| 二 | GitHub OAuth + 审核制 + 废弃邀请码 | 能用 GitHub 登录，pending 流程闭环 |
| 三 | 作品集首页 + /front 组件库展示 | 平台成形，可对外展示 |
| 四 | 服务器部署切换 + 旧容器下线 | 公网可访问，RAG 功能回归通过 |

每期结束都应保持"可部署、可回滚"的状态。
