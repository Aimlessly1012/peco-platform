# RAG 侧账号与访问控制

## Purpose
RAG 后端的访问守卫、会话归属与管理员用户管理。登录与准入自 M12 起由 unified-auth（平台 GitHub 登录）承担；M8 的邀请码/密码体系已废弃，未收录（历史见 archive）。

## Requirements

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

### Requirement: 用户列表（仅管理员）
系统 SHALL 提供 `GET /auth/users`（仅 admin，member 返回 403），返回全部用户：用户名、角色、
注册时间、最后登录时间、是否已禁用、所用邀请码（由 invite_codes.used_by 反查，管理员初始
账号无邀请码）、聊天会话数与提问数（用户维度聚合）。列表 SHALL 按注册时间倒序。

#### Scenario: 管理员查看用户画像
- **WHEN** admin 打开用户管理页
- **THEN** 看到每个用户的角色、注册与最后登录时间、来源邀请码、会话与提问数量

#### Scenario: member 无权查看
- **WHEN** member 调用用户列表接口
- **THEN** 403

### Requirement: 禁用与恢复登录权限
系统 SHALL 提供 `POST /auth/users/{id}/disable` 与 `POST /auth/users/{id}/enable`（仅 admin）。
禁用 SHALL 记录 disabled_at；被禁用用户 SHALL 立即无法通过守卫（即使其 JWT 尚未过期），
且无法登录（返回与密码错误相同的 401 文案，不泄露账号状态）。恢复后 SHALL 立即可用。
禁用 SHALL NOT 删除该用户的会话、消息或其创建的项目。

管理员 SHALL NOT 禁用自己，也 SHALL NOT 禁用最后一个处于启用状态的 admin（返回 400 并说明原因）。

#### Scenario: 禁用即刻生效
- **WHEN** 某 member 持有有效 JWT，管理员将其禁用
- **THEN** 该用户的下一个业务请求返回 401，无需等待 token 过期

#### Scenario: 禁用不丢数据
- **WHEN** 用户被禁用后再恢复
- **THEN** 其历史会话与消息完好，可继续使用

#### Scenario: 防自锁
- **WHEN** 管理员尝试禁用自己或最后一个启用的 admin
- **THEN** 400，且账号状态不变

#### Scenario: MCP 不受影响
- **WHEN** 账号被禁用，但编码 agent 使用 MCP_AUTH_TOKEN 接入
- **THEN** MCP 行为不变（独立鉴权体系）
