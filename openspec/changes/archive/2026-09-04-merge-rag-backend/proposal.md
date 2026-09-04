## Why

阶段二（8/22）把 RAG 前端迁入了 peco-platform，后端留在 `../RAG_coder`，迁移停在半路。
分裂已经产生实际代价：

- **平台自己的 spec 住在别人家**：`portfolio-platform` 等 8 个 capability 在 RAG_coder 的
  openspec 里，而平台代码在这边——这边的 openspec 昨天才初始化
- **JWS 是跨仓契约**：claim 名（`githubId`/`role`/`status`）与 HS256 算法两仓硬编码互相依赖，
  改一边另一边静默失效（CLAUDE.md 标注为「最容易踩的地方」）
- **部署靠 external network 缝合**：平台 compose 依赖 RAG compose 先起、提供 `rag_coder_default`
  网络，两套 compose 三个变体文件分居两仓
- **僵尸服务**：`RAG_coder/frontend/` 源码已从 git 树删除，磁盘只剩 `.next` 产物却仍在
  3300 端口运行十余天——无源码，不可重建不可修
- **CI 不对称**：RAG 有 `ci.yml` + 41 个测试文件，平台零 CI

方向已定（用户决策）：peco-platform 成为多项目单仓库，RAG 是第一个项目。

## What Changes

- `git subtree` 将 RAG_coder 并入本仓库，后端落位 `services/rag/`（66 个 py 文件 + 41 个测试）
- openspec 合并：8 个 capability 平移入根 `openspec/specs/`，未完结的 `m17-test-baseline` 随迁继续
- 编排统一到 `deploy/`：根 compose 用 `include:` 组织；**数据卷以卷级 `name:` 固定原名**
  （`rag_coder_pgdata` 等），伞项目改名不触碰数据；平台 compose 的 external network 依赖拆除
- nginx 配置随迁 `deploy/nginx/`（本次原样搬，按项目拆文件留给 platform-project-slots）
- `.github/workflows/ci.yml` 迁入，rag 测试按路径过滤触发
- 清理僵尸：`RAG_coder/frontend/` 磁盘残骸与 3300 端口进程
- 老仓库 GitHub 归档，README 留指针
- **纯拓扑纪律**：不改任何 API 行为、鉴权语义、业务代码——行为类改动（如删登录回退）归后续 change

## Capabilities

### New Capabilities

- `monorepo-layout`: 单仓多项目的拓扑约束——后端落位与构建自足、数据卷跨迁移连续、
  单一编排入口、openspec 单仓、迁移前后运行时行为不变、CI 随迁

（RAG 的 8 个既有 capability 以**文件平移**方式进入本仓库，不属于本 change 的 spec delta；
命名冲突暂不处理，`monorepo-layout` 与随迁的 `deployment` 日后如需合并另立 change。）

### Modified Capabilities

- `deployment`（随迁自 RAG）：「生产 Compose 与反代约束」条款更新——nginx 片段从 M7 宿主
  方式（`nginx-rag.conf`，已退役）改为容器化（`nginx/nginx-server.conf`），生产编排改为
  override 叠加形式；SSE 反代不缓冲的约束原样保留

## Impact

**新增**：`services/rag/`（自 RAG_coder/backend 平移）、`deploy/`（compose + nginx）、
`.github/workflows/ci.yml`、根 openspec 并入 8 个 capability

**修改**：`docker-compose.yml`（拆除 external network，并入统一栈）、`.dockerignore`（双向：
平台镜像排除 `services/`，rag 构建上下文自足）、README 架构段

**不动**：`app/` `components/` `lib/` 的任何业务代码；`/rag/api` 的任何行为；MCP 端点 URL

**外部动作**：服务器一次切换窗口（需用户在场）；老仓库归档；本地 3300 进程终止

**已知风险摘要**（详见 design）：卷名对不上 = 数据「消失」是唯一的数据级风险，
用「卷级 name 固定 + 切换清单前后快照比对」双保险覆盖。
