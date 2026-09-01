# Tasks: M11 用户管理（B=后端 / F=前端 / V=PM 验收）

## 1. 后端 B 组

- [x] B1 模型与迁移：users 加 disabled_at / last_login_at（均可空）；alembic 0008
- [x] B2 登录写 last_login_at；被禁用账号登录返回与密码错误相同的 401 文案；单测
- [x] B3 守卫校验禁用态：require_user 解析 JWT 后查库确认 disabled_at IS NULL，禁用即刻 401（不等 token 过期）；单测覆盖"持有效 token 被禁后立即失效"
- [x] B4 GET /auth/users（admin）：用户名/角色/注册时间/最后登录/禁用态/所用邀请码（invite_codes 反查）/会话数/提问数，注册时间倒序；member 403；单测
- [x] B5 disable / enable 接口（admin）+ 两条护栏：不能禁自己、不能禁最后一个启用的 admin（400）；单测覆盖两条护栏与禁用不丢数据
- [x] B6 现有 553 测试保持全绿

## 2. 前端 F 组

- [x] F1 /users 管理页（admin）：表格（用户名/角色/注册/最后登录/邀请码/会话数/提问数/状态）+ 禁用/恢复按钮（禁用需二次确认），被禁用行灰显；member 访问跳首页
- [x] F2 TopNav 加「用户」入口（仅 admin，与「邀请码」并列）；build 两形态过

## 3. V 组（PM 验收）

- [x] V1 全量单测绿 + 前后端 build + 容器代码核验
- [x] V2 本地实测：admin 看列表数据准确（邀请码反查、计数）→ 禁用 member → member 持旧 cookie 立即 401 且无法重新登录 → 恢复后可用；自锁护栏两条都拦
- [x] V3 服务器上线（查 indexing 后重建）+ 公网复测 + MCP/登录回归
- [x] V4 提交；归档由用户触发
