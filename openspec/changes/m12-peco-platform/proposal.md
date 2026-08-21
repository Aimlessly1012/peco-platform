# M12: peco-platform —— RAG Coder 演进为个人作品集平台

## Why

RAG Coder 已在服务器上稳定运行（M7-M11），但它现在是一个孤立的工具站：
- 用自建的用户名密码 + 邀请码准入（M8），与用户其他项目各自为政
- 服务器根路径空着（zc_erp 已下线），作品集无处安放
- heitu 组件库（FormRender / charts）没有展示入口

用户决定**重构成统一平台**：一个前端、一次登录、统一视觉，把 RAG Coder 与 heitu 组件库
都收进去作为作品展示。原 x-blog 的博客功能废弃，但其 NextAuth GitHub 登录与审核制
（pending/approved/rejected）的思路保留——它正好取代 RAG 现有的邀请码体系。

## What Changes

### 新建仓库 peco-platform（Next.js 15 单体）

| 路由 | 内容 |
|------|------|
| `/` | 作品集首页 |
| `/login` | GitHub OAuth 登录（NextAuth） |
| `/pending` | 待审核页（申请人登录后落这里） |
| `/front` | heitu 组件库展示（文档 + demo，antd 配终端风 token） |
| `/rag/*` | RAG Coder 全部页面（自 RAG_coder/frontend 迁入） |
| `/admin` | 用户审核（待审红点提醒） |

### RAG_coder 仓库（后端保留，只改鉴权）

- **废弃** M8 的密码登录、邀请码注册、`/auth/register`、`/auth/invites`
- **保留** users 表与 M11 的用户管理（角色、禁用、会话归属），身份来源换成 GitHub
- 鉴权改为验证平台传来的 NextAuth 会话
- 前端目录迁出（页面搬进平台），仓库变为纯后端服务

## 关键决策与理由

**后端不合并**：FastAPI + LangGraph + Neo4j + tree-sitter 是 Python 生态，无法塞进
Next.js，重写没有意义——那是本系统最核心的资产。前后端分离本就是正常架构。

**统一视觉靠设计令牌而非重写**：RAG 前端是 Tailwind + CSS 变量，antd 有 ConfigProvider
token 系统。定义一套终端风令牌两边各配一次即可统一，页面结构与交互逻辑原样迁移。

**申请功能即审核制**：GitHub 登录后 status=pending，管理员批准即可用。不需要邀请码，
也不需要把任何东西发给申请人（这正是统一登录带来的简化）。

## 不做什么（本期）

- **不做微信通知**：申请只在 `/admin` 红点提醒，推送通道留接口口子，以后再加
- 不迁移 x-blog 的博客/早报/作者功能与数据（已废弃）
- Neo4j 不动（图谱是 RAG 专用）

## Capabilities

- `portfolio-platform`（ADDED）：作品集平台的路由、首页、组件库展示
- `unified-auth`（ADDED）：GitHub OAuth + 审核制 + 跨服务鉴权
- `code-chat`（MODIFIED）：前端迁入平台，鉴权来源变更

## 风险

- **GitHub OAuth 回调地址**：目前只有 IP（`http://43.167.170.20/api/auth/callback/github`），
  以后加域名要回 GitHub 后台改一次
- **迁移期双站并存**：平台上线前 RAG 现有前端要保持可用，切换需要一次原子的 nginx 变更
- 现有 5 个测试账号作废（改用 GitHub 登录，重新申请即可）
