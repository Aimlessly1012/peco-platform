# M8: 邀请码准入（管理员 + 邀请码注册）

## Why

M7 上线公网（http://43.167.170.20/rag）后系统对全网裸奔——任何人都能建项目、触发索引（烧硅基流动 key 的钱）、读代码问答。需要最小可用的准入控制。用户已确认三个决策：

1. **邀请码注册账号**：用户名+密码+邀请码注册，之后账号登录（邀请码一次性）
2. **普通用户全功能除管理**：能建项目/索引/聊天/看报告；不能删项目、不能管邀请码
3. **项目全局共享**：所有人同一份项目列表；聊天会话按人独立

## What Changes

| # | 变更 | 说明 |
|---|------|------|
| 1 | users / invite_codes 表 + chat_sessions.user_id | alembic 迁移；旧会话 user_id NULL 视为管理员的 |
| 2 | 管理员初始化 | env `ADMIN_USERNAME` / `ADMIN_PASSWORD`，首次启动无 admin 时创建（bcrypt 入库）；之后 env 改动不覆盖 |
| 3 | 认证 API | `/auth/login`（JWT → httpOnly cookie）、`/auth/register`（消耗邀请码）、`/auth/me`、`/auth/logout` |
| 4 | 邀请码管理 API | admin 生成/列表（含使用状态与使用者）；一次性消耗 |
| 5 | 全站守卫 | 业务路由未登录 401；`DELETE /projects/*` 与邀请码管理仅 admin。**豁免**：/auth/*、/health、**/mcp（保持独立 Bearer token 机制不变）** |
| 6 | 前端 | /login 登录+注册页、未登录路由守卫、TopNav 用户名/登出、admin 的邀请码管理页、会话列表按人过滤 |

## 不做什么（v1 克制）

- 不做密码找回/修改、邮箱验证、登录限速、审计日志
- 不做用户管理页（邀请码列表即用户清单雏形）
- 不做项目按人隔离（已确认共享）
- MCP 接入方式完全不动

## Capabilities

- `auth`（ADDED）：账号/邀请码/会话/守卫
- `code-chat`（MODIFIED）：会话归属用户
- `project-management`（MODIFIED）：删除仅 admin

## 风险

- 前端所有 fetch/SSE 需带 cookie（同域默认带；本地开发跨端口 3200→9200 需 credentials + CORS allow_credentials）
- 子路径部署 cookie path 必须覆盖 /rag 与 /rag/api（设 path=/）
- 服务器已有测试数据：旧会话 NULL 归 admin，不迁移不丢
