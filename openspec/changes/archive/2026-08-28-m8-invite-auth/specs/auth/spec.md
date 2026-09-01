# auth — 邀请码准入（M8 新增能力）

## ADDED Requirements

### Requirement: 管理员初始化
系统 SHALL 在启动时检查 users 表：不存在 admin 角色用户且 `ADMIN_PASSWORD` 非空时，用 `ADMIN_USERNAME`（默认 admin）创建管理员（密码 bcrypt 哈希入库）；已存在 admin 后环境变量变更 SHALL NOT 覆盖库中账号。`ADMIN_PASSWORD` 为空时跳过创建并记录 warning，系统正常启动。

#### Scenario: 首次启动创建管理员
- **WHEN** 全新库首次启动且 .env 配置了 ADMIN_PASSWORD
- **THEN** users 表出现 role=admin 的记录，可用该账号登录

### Requirement: 邀请码注册与登录
系统 SHALL 提供：`POST /auth/register`（用户名+密码+邀请码；邀请码必须存在且未使用，注册成功即标记 used 并绑定使用者，账号 role=member，随即下发登录态）；`POST /auth/login`（校验失败统一返回 401「用户名或密码不正确」，不区分哪项错误）；`GET /auth/me`；`POST /auth/logout`。登录态 SHALL 为 JWT（HS256 + SECRET_KEY，7 天过期）经 httpOnly SameSite=Lax Path=/ cookie 下发。

#### Scenario: 邀请码一次性
- **WHEN** 两人先后用同一枚邀请码注册
- **THEN** 第一人成功，第二人被拒绝且提示邀请码已被使用

#### Scenario: 无效登录不泄露信息
- **WHEN** 用户名不存在或密码错误
- **THEN** 均返回 401 与同一提示文案

### Requirement: 邀请码管理（仅管理员）
系统 SHALL 提供 `POST /auth/invites`（生成 8 位去易混字符邀请码）与 `GET /auth/invites`（列表含 code、是否已用、使用者用户名、时间），两者仅 admin 可用，member 访问返回 403。

#### Scenario: member 无法管理邀请码
- **WHEN** member 登录态调用邀请码接口
- **THEN** 403

### Requirement: 全站访问守卫
除 `/auth/login`、`/auth/register`、`/health`、`/mcp`（保持既有独立 Bearer token 鉴权）外，业务 API SHALL 要求有效登录态，未登录返回 401「请先登录」。`DELETE /projects/{id}` SHALL 仅 admin 可用。前端 SHALL 在未登录时跳转 /login，member 界面不显示删除入口。

#### Scenario: 未登录被拦
- **WHEN** 无 cookie 直接调用 GET /projects
- **THEN** 401；浏览器端跳转登录页

#### Scenario: MCP 接入不受影响
- **WHEN** 编码 agent 以既有 MCP_AUTH_TOKEN Bearer 方式接入 /mcp
- **THEN** 行为与 M7 一致，不需要账号登录态

### Requirement: 聊天会话归属
新建聊天会话 SHALL 记录 user_id；会话列表 SHALL 只返回当前用户的会话（user_id 为 NULL 的历史会话仅 admin 可见）；访问他人会话的消息或提问 SHALL 返回 404。项目、报告、功能地图数据保持全局共享。

#### Scenario: 会话按人隔离
- **WHEN** 用户 B 请求用户 A 创建的会话消息
- **THEN** 404，B 的会话列表也不出现该会话
