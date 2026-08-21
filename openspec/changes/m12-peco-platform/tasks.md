# Tasks: M12 peco-platform（P=平台 / B=RAG 后端 / D=部署 / V=验收）

## 阶段一：平台骨架上线（`/rag` 保持现状不受影响）

- [x] P1 新建 peco-platform 仓库：Next.js 15 + TypeScript + Tailwind，落终端风设计令牌（paper/ink/accent、IBM Plex Mono、无圆角），与 RAG 现有令牌同源
- [x] P2 NextAuth + GitHub Provider：JWT strategy、jwt 回调每次查库取最新 status；`ADMIN_GITHUB_ID` 指定管理员；登录页与 pending 页
- [x] P3 users 表迁移（Postgres，与 RAG 共用库）：github_id/name/avatar_url/role/status/disabled_at/last_login_at；首次登录 upsert 建 pending 记录
- [x] P4 `/admin` 用户审核页：待审列表 + 红点提醒、批准/拒绝/禁用；仅 admin 可见
- [x] P5 作品集首页 `/`：作品卡片（RAG Coder、heitu 组件库），终端风
- [x] P6 `/front` 组件库展示：heitu 以 git 依赖引入，antd ConfigProvider 适配终端风 token，FormRender 与 charts 各一个可交互 demo
- [x] D1 平台容器化 + nginx 根路径接管（`/rag` 仍指向旧前端容器，两者共存）
- [x] V1 阶段一验收：GitHub 登录 → pending → 批准 → 可进；`/front` demo 可用；`/rag` 旧站不受影响

## 阶段二：RAG 页面迁入与鉴权切换

- [x] P7 RAG 前端页面迁入 `/rag/*`：项目列表、项目详情三页签（含 markmap/mermaid/进度条）、聊天页（SSE + 引用联动）、MCP 说明页；只统一令牌，不改结构与交互
- [x] P8 平台侧 `/rag/api/*` 代理：签发内部令牌转发后端；**重点验证 SSE 流式（聊天 token、索引进度）与 MCP 长连接不被代理破坏**
- [x] B1 RAG 后端接受内部令牌：共享密钥验签 + 校验 status/禁用态；迁移期保留密码登录作为退路
- [x] B2 users 表对齐：加 github_id、去 password_hash 依赖；chat_sessions.user_id 关系不变
- [x] V2 阶段二验收：RAG 全功能回归（录入/索引进度/报告各图/聊天流式/引用联动/MCP 接入）；未批准与被禁用用户被挡

## 阶段三：清理

- [ ] B3 删除 M8 的密码登录、注册、邀请码接口与 invite_codes 表；删除 RAG_coder/frontend 目录
- [ ] D2 nginx 切换：`/rag` 归平台内部路由，旧前端容器下线
- [ ] V3 全站复测 + 提交归档
