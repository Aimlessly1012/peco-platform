## 1. 预检（无破坏、完全可逆，可立即执行）

- [x] 1.1 落盘数据基线到 `deploy/migration-baseline.md`：`docker volume ls` 全量、`platform_users` 行数、Neo4j 节点数、MinIO bucket 对象数——切换验证以此为准，不靠临场记忆
- [x] 1.2 确认 `m17-test-baseline` 当前状态（tasks 进度、是否有未提交工作），记录「随迁继续」的交接说明
- [x] 1.3 终止本地 3300 进程（PID 48629；后端已核实本地无 nginx 等消费方，杀进程安全）。**目录删除移至 6.4**——standalone 无源码不可重建，删除不可逆，留到切换观察期结束；原任务把第 1 组标为「完全可逆」对此项不成立，已修正
- [x] 1.4 冻结旧仓库：RAG_coder 自此不再接受新提交。未提交内容的处置（等用户确认）：`projects.py` 纯格式化改动建议丢弃（与 m15 的 108 行同类，无逻辑变更）；含本机绝对路径的 `.claude/launch.json` 不入库

## 2. subtree 并入（git 操作，独占工作区——执行期间另一会话不得写本仓库）

- [x] 2.1 确认分支基线已决（design 的 Open Question：建议 m15 先合 main），从基线开新分支
- [x] 2.2 `git subtree add` 并入 RAG_coder（message 写明来源仓库与源 HEAD 的 commit 号）
- [x] 2.3 目录落位（一个独立 commit，git 可跟踪 rename）：`backend/*` → `services/rag/`；RAG 的 `openspec/specs/*` 并入根 `openspec/specs/`；`openspec/changes/m17-test-baseline` 并入根 `changes/`；`deploy/*` 与三个 compose 变体 → `deploy/`；`docs/` → `services/rag/docs/`；旧仓库级杂物（README、`.env.example`）内容合并后删除
- [x] 2.4 `.github/workflows/ci.yml` 迁入：rag 测试 job 加 `paths: services/rag/**` 过滤，工作目录与缓存路径修正
- [x] 2.5 全文搜索 `\.\./RAG_coder|\./backend` 清残留路径引用

## 3. 编排统一

- [x] 3.1 `deploy/docker-compose.yml`：顶层 `name: peco` + `include:` 列表 + 共享 db；`deploy/compose/rag.yml`（backend/worker/neo4j/rabbitmq/minio）、`deploy/compose/platform.yml`
- [x] 3.2 四个数据卷加卷级 `name:` 固定原名（`rag_coder_pgdata` / `neo4jdata` / `miniodata` / `rabbitmqdata`）
- [x] 3.3 相对路径修正：rag 的 `build.context` → `./services/rag`，`data/repos` 挂载路径随仓库根调整
- [x] 3.4 平台服务并入同栈：删除旧 `docker-compose.yml` 的 `external: true` 网络与 `127.0.0.1:3200` 单独编排，端口绑定策略保持（公网仍一律经 nginx）
- [x] 3.5 nginx 配置随迁 `deploy/nginx/`，活配置**原样**搬（按项目拆文件归 platform-project-slots）；`nginx-rag.conf`（M7 时代、全仓无任何 compose 挂载的死文件）不随迁为活配置——移入 `deploy/server-notes/` 或删除
- [x] 3.6 `docker compose config` 渲染检查：四个卷名逐一比对 1.1 基线、构建上下文路径、端口无冲突
- [x] 3.8 修复搬家打断的路径计算：`services/rag/tests/test_regression_guards.py` 的 `REPO_ROOT`（`BACKEND_DIR.parent` → 需再上一级）——搬家后指向 `services/`，`.env` 隔离门禁在本地与 CI 双双 `pytest.skip` 静默空转（R5 同类：不崩不红只是不干活）。同 commit 内并扫 `services/rag` 全部从 `__file__` 推仓库根的表达式（`.parent` 链 / `parents[n]`）逐个核对语义。**验收 = 原先被跳过的护栏测试真实执行且通过，不再 skip**
- [x] 3.9 **生产栈统一为 override**（裁定采后端方向 2）：`docker-compose.prod.yml` 从完整定义改写为叠加层（`-f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml -f deploy/docker-compose.server.yml`），platform 随伞文件自动进入生产栈，两 compose 项目并存与 external network 缝合在生产侧一并消失。**已知陷阱**：compose 对 list 型字段（ports/volumes）是合并追加不是替换——去掉 db/neo4j 宿主端口要用 `!reset`/`!override` 标签，先确认服务器 docker compose 版本支持；不支持则改用倒置结构（base 无端口、dev 覆盖层加端口）。**验收 = render-diff**：改写前后各渲染一次生产栈 `config`，diff 里只允许出现两类意图内差异（platform 服务加入、external network 消失），其余逐字节一致，四卷仍为 `rag_coder_*`
- [x] 3.10 deployment capability 的 spec delta：「生产 Compose 与反代约束」条款改为容器化现实（nginx-rag.conf → nginx/nginx-server.conf，prod 改 override 形式），SSE 不缓冲约束原样保留——架构会话起草，后端复核
- [x] 3.7 `.dockerignore` 双向修正：平台镜像排除 `services/` `deploy/` `openspec/`；rag 上下文排除无关目录。验收 = 两个镜像构建成功且体积无异常膨胀

## 4. 本地全栈验证

- [ ] 4.1 `docker compose up -d` 起全栈，`docker volume ls` 与基线比对：**零新增 rag 相关卷**；`platform_users` 行数与 Neo4j 节点数与 1.1 一致
- [ ] 4.2 端到端冒烟：登录 → `/rag` 项目列表 → 详情 → chat 一轮 SSE 流式问答（引用联动正常）；MCP 端点可达
- [x] 4.3 `services/rag` 下 pytest 全绿；`npm run lint`、`npm run build`、`npm run check:reference` 全绿
- [x] 4.4 openspec 在新仓库可用：`openspec list` 见 m17-test-baseline ✓。校验标准修正为**与迁移前一致**：`--all --strict` 下 6 个随迁 spec 失败（缺 `## Purpose` 段），对照冻结旧仓库同样 6 个——搬家前既有，非搬家所致；本仓库自有 change 全部 strict 通过。修复 6 个 spec 另立 change

## 5. 服务器切换（需用户在场的窗口，每步有回退点）

- [ ] 5.1 服务器落盘同款数据基线（卷列表 + 行数/节点数）
- [ ] 5.2 拉取新仓库；`docker compose config` 渲染检查卷名（up 之前，纸面上就能看出错）
- [ ] 5.3 down 旧栈 → 从 `deploy/` up 新栈 → 比对基线 → nginx 生效
- [ ] 5.4 线上冒烟：`/`、`/login`（OAuth 回调）、`/rag` 全链路、MCP 端点
- [ ] 5.5 旧部署目录保留一周观察期，期间旧仓库只读
- [ ] 5.6 nginx 一致性确认（切换窗口内，轻量）：`nginx -T` 比对服务器生效配置与 `deploy/nginx-server.conf` 一致。预检时「线上或仍跑旧前端」的判断**有误已更正**：`8e0c946`（8-22）已把 `/rag` 归平台并附公网复测；`nginx-rag.conf` 是 M7 时代无消费者的死文件（见 migration-baseline §5.2）
- [ ] 5.7 MinIO 链路功能验证：切换后触发一次小型索引，确认 `rag-artifacts` 有对象落桶——基线时桶为空（0 对象），**空桶不作为「数据没丢」的证据**

## 6. 收口

- [ ] 6.1 老仓库 GitHub archive，README 首行加指针「已并入 peco-platform，历史见本仓库或新仓库 `services/rag`」
- [x] 6.2 CLAUDE.md「边界：后端不在这个仓库」章节反转重写（本地文件，随维护者）。实际改了五处而非一处：命令节补后端/编排、CI 表述、边界章节反转、鉴权的跨仓路径、构建部署的 external network 段
- [ ] 6.3 README 架构段更新：三仓图 → 单仓多项目图；`openspec validate --strict` 收尾通过
- [x] 6.5 `deploy/DEPLOY.md` 顶部加过时横幅：全文描述的是 M7 宿主 nginx 部署方式，已被容器化 nginx 取代——一段声明 + 指向现行方式（migration-baseline 与第 5 组清单），**不重写正文**（内容变更超出本 change）
- [ ] 6.4 删除 `../RAG_coder/frontend/` 磁盘残骸（1.1G；5.5 观察期结束后执行，自 1.3 移入）
