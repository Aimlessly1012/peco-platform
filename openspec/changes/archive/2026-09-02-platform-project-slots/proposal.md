## Why

用户方向：平台后续会持续新增项目（路由）。今天「新增一个项目」要摸着 RAG 的脚印散改
一堆既有文件——TopBar 与首页硬编码导航、middleware matcher 手写且藏着裸路径陷阱
（`"/rag/:path*"` 匹配不到 `/rag`，commit `6eaef3d` 踩过，会随每个新项目重复一次）、
nginx 与 compose 要编辑主文件、鉴权契约（JWS claim 名、算法、「登录直走一套」）只存在于
一个**未入版本库**的本地 CLAUDE.md 里。

N 个项目的正确默认值是：**新增项目 = 新增文件 + 三处受守卫的登记**（注册表、matcher、compose include），而不是散改现场。

## What Changes

- 新增 `lib/projects.ts` 项目注册表（key / label / route / access / backend），成为项目清单的
  唯一事实源；TopBar 导航与首页项目区改为从注册表渲染
- middleware 的访问判断按注册表执行（public / approved / admin 三级）；matcher 受 Next 静态
  限制仍手写，但新增**守卫脚本**：凡非 public 项目，裸路径与 `:path*` 两条缺一即非零退出，
  接入 CI——`6eaef3d` 那个坑从此有机器盯着
- nginx 拆为 `include projects/*.conf`，compose 沿用 A 的按项目文件——新增项目不再编辑主文件
- 新增 `project-onboarding` capability spec：登录直走一套（项目 MUST NOT 自建登录；后端
  MUST 验平台 JWS）+ 七步接入清单，契约从「未入库的部落知识」升格为版本库里的 spec

## Capabilities

### New Capabilities

- `project-registry`: 注册表作为项目清单唯一事实源、访问级别的双层执行、matcher 覆盖的机器守卫、
  「新增项目仅新增文件」的结构约束
- `project-onboarding`: 平台统一登录契约（JWS 验签、禁止自建鉴权）与可执行的接入清单

### Modified Capabilities

（无。RAG 随 merge-rag-backend 迁入的 8 个 capability 不在本 change 修改；
删除登录回退等行为改动归后续 change C，届时以 delta 修改 `project-onboarding`。）

## Impact

**新增**：`lib/projects.ts`、`scripts/check-middleware.mjs`、`deploy/nginx/projects/*.conf`、
`openspec/specs/project-onboarding`（随本 change 的 delta 归档生成）

**修改**：`components/TopBar.tsx`、`app/page.tsx`（首页项目区）、`middleware.ts`（判断逻辑
读注册表；matcher 本身仅核对不重写）、`.github/workflows/ci.yml`（挂守卫）、`package.json`

**依赖**：merge-rag-backend 先落地（nginx / compose / CI 文件都住在它创建的 `deploy/` 与
`.github/` 里）

**明确不做**：插件系统、动态路由注册、turborepo/nx、共享组件包——N 预计 2~4，
注册表 + 守卫脚本是抽象的上限。
