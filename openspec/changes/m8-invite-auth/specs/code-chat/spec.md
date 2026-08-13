# code-chat — 会话归属（M8）

## MODIFIED Requirements

### Requirement: 聊天会话管理
聊天会话 SHALL 归属创建它的登录用户（user_id）；会话列表接口 SHALL 只返回当前用户的会话，user_id 为 NULL 的历史会话仅 admin 可见；对他人会话的消息读取与提问 SHALL 返回 404（不泄露存在性）。会话的创建、提问、SSE 流式与引用行为保持不变。

#### Scenario: 会话按人隔离
- **WHEN** 用户 B 列出会话或访问用户 A 的会话
- **THEN** 列表不含 A 的会话；直接访问返回 404
