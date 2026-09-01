# unified-auth — 统一认证与准入（M12 新增能力）

## ADDED Requirements

### Requirement: GitHub 登录与审核准入
平台 SHALL 以 GitHub OAuth 作为唯一登录方式（NextAuth）。首次登录 SHALL 建立
`status=pending` 的用户记录并落到待审核页；管理员在 `/admin` 批准后 SHALL 立即生效
（会话回调每次读取最新状态，不等 token 过期）。被拒绝或禁用的用户 SHALL 无法访问
受保护路由。管理员账号由 `ADMIN_GITHUB_ID` 环境变量指定。

#### Scenario: 申请与批准
- **WHEN** 新访客用 GitHub 登录
- **THEN** 落在待审核页，`/admin` 出现一条待审记录与红点提醒；管理员批准后该用户
  刷新即可访问全部受保护功能

#### Scenario: 审核状态即时生效
- **WHEN** 管理员把某已批准用户改为拒绝或禁用
- **THEN** 该用户的下一次请求即被挡下，无需等待登录态过期

### Requirement: 跨服务鉴权
平台 SHALL 在转发到 RAG 后端时签发短时效内部令牌（含 github_id、role、status），
后端 SHALL 用共享密钥验签并校验 status 与禁用态。RAG 后端 SHALL NOT 再提供密码登录、
邀请码注册与邀请码管理接口。MCP 端点 SHALL 继续使用独立的 `MCP_AUTH_TOKEN` 机制，
不受账号体系影响。

#### Scenario: 后端拒绝无效身份
- **WHEN** 请求携带过期、伪造或状态非 approved 的内部令牌
- **THEN** 后端返回 401，不泄露账号是否存在

#### Scenario: MCP 接入不受影响
- **WHEN** 编码 agent 以 MCP_AUTH_TOKEN 接入
- **THEN** 行为与 M7/M8 一致，无需任何账号登录态
