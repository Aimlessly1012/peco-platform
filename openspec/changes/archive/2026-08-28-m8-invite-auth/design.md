# M8 设计

## D1 数据模型（alembic 0007）

```
users:         id(uuid) | username(unique, 3-32) | password_hash | role(admin|member) | created_at
invite_codes:  id(uuid) | code(unique, 8位大写字母数字) | created_by(fk users) | used_by(fk users, null) | used_at(null) | created_at
chat_sessions: + user_id(fk users, nullable)   # NULL = 历史数据，视为管理员的
```

- 密码 bcrypt（passlib[bcrypt]）；邀请码 `secrets.choices` 8 位去易混字符（无 0O1lI）
- 依赖新增：`passlib[bcrypt]`、`pyjwt`（均轻量、无系统依赖）

## D2 管理员初始化（lifespan）

启动时若 users 表无 admin 角色记录：用 `ADMIN_USERNAME`（默认 admin）+ `ADMIN_PASSWORD` 创建。
`ADMIN_PASSWORD` 为空则跳过创建并 warning（系统照常起，但登录不进去——.env.example 注明必填）。
已有 admin 后 env 改动不生效（防止重启覆盖改过的密码）。

## D3 认证与会话

- JWT：HS256 + 现有 SECRET_KEY，payload {sub: user_id, role, exp: 7d}
- 下发：`Set-Cookie: rag_token=<jwt>; HttpOnly; SameSite=Lax; Path=/; Max-Age=7d`
  （不设 Secure——当前 HTTP 部署；上 HTTPS 后加，DEPLOY.md 记一笔）
- API：
  - `POST /auth/login {username, password}` → 200 set-cookie + {username, role}；失败统一 401「用户名或密码不正确」
  - `POST /auth/register {username, password, invite_code}` → 校验邀请码未用 → 建号（role=member）+ 标记邀请码 used → 直接 set-cookie 登录态
  - `GET /auth/me` → {username, role}（前端守卫探测用）
  - `POST /auth/logout` → 清 cookie
  - `POST /auth/invites`（admin）→ 生成一枚；`GET /auth/invites`（admin）→ 列表 [{code, used_by_name, used_at, created_at}]

## D4 守卫（FastAPI 依赖，不用全局中间件）

`require_user` / `require_admin` 两个依赖，挂到路由级：

- 业务路由（projects / sessions / report / modules / jobs / mcp-info）全部 `require_user`
- `DELETE /projects/{id}`、`/auth/invites*` 挂 `require_admin`
- **豁免**：`/auth/login|register`、`/health`、`/mcp`（MCP 子应用是 ASGI mount，依赖注入进不去也不需要——独立 Bearer token 已有，M7 刚修过 root_path 匹配）
- cookie 无/过期/伪造 → 401 {detail: "请先登录"}；前端拦 401 统一跳 /login
- 会话归属：`POST /projects/{id}/sessions` 写 user_id=当前用户；`GET /projects/{id}/sessions` 只回 `user_id = 当前用户 OR (user_id IS NULL AND role=admin)`；`/sessions/{id}/ask|messages` 校验归属（404 掩护，不泄露他人会话存在性）

## D5 前端

- `/login`：登录/注册双 tab（注册多一个邀请码输入）；成功后回跳来源页
- 守卫：根布局挂 `AuthProvider`——`GET /auth/me` 401 → `router.replace("/login")`；api.ts fetch 统一 `credentials: "include"`（SSE fetch 同）+ 401 响应统一跳登录
- TopNav：右侧显示用户名 + 登出；admin 加「邀请码」入口
- `/invites`（admin）：生成按钮 + 列表（码/状态/使用者/时间，未用的可一键复制）
- member 隐藏项目卡片的删除按钮（后端 403 兜底）

## D6 CORS 与部署形态

- 本地开发跨端口（3200→9200）：CORSMiddleware 加 `allow_credentials=True`（origin 已是精确列表，合规）
- 生产同域（/rag → /rag/api）cookie 自动带，无 CORS 参与
- .env.example 加 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 段；服务器 .env 同步补齐后重建 backend

## D7 验收口径

- 单测：注册（含邀请码已用/不存在）、登录成败、JWT 过期、require_admin 拦 member、会话归属过滤、旧会话 NULL 兼容、/health 与 /mcp 豁免
- 手测：未登录访问任意页跳 /login；member 删项目 403 且无删除按钮；admin 生成邀请码 → 无痕窗口注册登录全流程；服务器公网复测 + MCP token 接入不受影响
