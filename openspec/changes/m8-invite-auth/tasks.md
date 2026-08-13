# Tasks: M8 邀请码准入（B=后端 / F=前端 / V=PM 验收）

## 1. 后端 B 组

- [x] B1 依赖与模型：pyproject 加 passlib[bcrypt] + pyjwt；tables.py 加 User / InviteCode、ChatSession.user_id(nullable)；alembic 0007 迁移
- [x] B2 安全基件（services/auth/security.py）：bcrypt 哈希/校验、JWT 签发/解析（HS256 + SECRET_KEY、7d）、邀请码生成（8 位去易混 secrets）；单测
- [x] B3 管理员初始化：lifespan 无 admin 且 ADMIN_PASSWORD 非空时创建；env 后续变更不覆盖；.env.example 加 ADMIN_USERNAME/ADMIN_PASSWORD 段；单测
- [x] B4 认证 API（api/auth.py）：login（统一 401 文案）/ register（消耗邀请码，事务内防并发双花）/ me / logout；httpOnly SameSite=Lax Path=/ cookie；单测覆盖注册成败/一次性/登录成败
- [x] B5 邀请码管理 API：POST/GET /auth/invites 仅 admin（403 拦 member）；列表含使用状态与使用者名；单测
- [x] B6 守卫接线：require_user / require_admin 依赖；业务路由全挂 require_user（/auth/*、/health、/mcp 豁免）；DELETE /projects 挂 require_admin；CORS 加 allow_credentials=True；单测覆盖未登录 401、member 删项目 403、/health 与 /mcp 豁免
- [x] B7 会话归属：创建会话写 user_id；列表按人过滤（NULL 仅 admin 可见）；他人会话 ask/messages 404；单测

## 2. 前端 F 组

- [x] F1 api.ts：fetch 与 SSE 统一 credentials: "include"；401 统一跳 /login（保留回跳地址）
- [x] F2 /login 页：登录/注册双 tab（注册含邀请码输入），终端风设计令牌；成功回跳
- [x] F3 AuthProvider 守卫 + TopNav：/auth/me 探测、未登录 replace 到 /login；TopNav 右侧用户名 + 登出 + admin 的「邀请码」入口
- [x] F4 /invites 管理页（admin）：生成按钮、列表（码/状态/使用者/时间）、未用码一键复制；member 访问跳首页
- [x] F5 member 隐藏项目删除按钮；npm run build 两形态过
- [x] F6 聊天打字机平滑渲染（用户追加）：SSE token 进缓冲队列，按稳定速率逐字消费渲染（推理型模型 token 爆发式涌出，直渲染是"一坨全出"）；积压大时自适应加速追赶，done 事件立即 flush 余量，切换会话/新提问清队列；滚动跟随不抖动
- [x] F7 聊天等待 loading 动画（用户追加）：发送后到首 token 前的等待期（线上大项目实测 25-30s）显示终端风 loading——闪烁光标/滚动点 + 阶段文案（如「正在检索代码…」），收到 SSE ping 心跳视为连接正常；首 token 到达即切流式渲染；报错显示错误态。与 F6 的缓冲渲染衔接自然

## 3. V 组（PM 验收）

- [x] V1 全量单测绿 + 前后端 build + 容器代码核验
- [x] V2 本地全流程：admin 登录 → 生成邀请码 → 无痕注册 member → member 建项目/聊天可用、删项目 403、邀请码页被拒；会话互不可见；未登录全站跳登录
- [ ] V3 服务器上线：.env 补 ADMIN_* → 重建 backend/frontend → 公网复测登录/注册/聊天 SSE；MCP token 接入回归不受影响
- [ ] V4 提交；归档由用户触发
