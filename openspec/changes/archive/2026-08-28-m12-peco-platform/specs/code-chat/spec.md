# code-chat — 前端迁移与鉴权变更（M12）

## MODIFIED Requirements

### Requirement: 聊天会话管理
聊天会话仍 SHALL 归属登录用户并按用户隔离（他人会话 404），但用户身份 SHALL 来自平台的
GitHub 登录态（经内部令牌传递），不再来自 RAG 自建的密码账号。前端聊天页 SHALL 位于平台
`/rag/chat` 路由下，SSE 流式、阶段展示、`[n]` 引用联动行为保持不变。

#### Scenario: 会话隔离在新身份体系下成立
- **WHEN** 两个 GitHub 用户各自在 `/rag` 发起会话
- **THEN** 彼此看不到对方的会话，访问他人会话返回 404
