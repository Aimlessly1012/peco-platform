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

- [x] 4.1a（4.1 实施中追加）nginx 平台上游写死了旧容器名 `peco-platform-platform-1`——统一栈里容器名为 `peco-platform-1`、服务名 `platform`，切换后首页会 502。已改为服务名（`39374a1`）。本地 E2E 用 nginx 挂 3000 的覆盖层（scratchpad）复刻 server.yml 的挂载结构，使 OAuth 回调、同源 `/rag/api`、SSE 走真实 `projects/rag.conf` 三者同时成立
- [x] 4.1 `docker compose up -d` 起全栈，`docker volume ls` 与基线比对：**零新增 rag 相关卷**；`platform_users` 行数与 Neo4j 节点数与 1.1 一致
- [x] 4.2 端到端冒烟（用户真人登录态走完）：GitHub OAuth 回调 302 → 审核台/项目列表/三个项目详情/报告/模块 全部 200；`/rag/api/*` 经 nginx 20 次 200 / 0 次 401（JWS 跨服务验签成立）；触发一次全量索引 → worker 经 RabbitMQ 接单跑完、MinIO 落 3 个对象（5.7 提前达成）；chat `/ask` 经 nginx 200 / 9.5KB，后端调 LLM 4×200，回答落库；会话删除 5×204 顺带回归。发现并修：DeepSeek key 失效（老 .env 原样搬来，线上疑同）、ADMIN_GITHUB_ID 数字占位、nginx 平台上游旧容器名
- [x] 4.3 `services/rag` 下 pytest 全绿；`npm run lint`、`npm run build`、`npm run check:reference` 全绿
- [x] 4.4 openspec 在新仓库可用：`openspec list` 见 m17-test-baseline ✓。校验标准修正为**与迁移前一致**：`--all --strict` 下 6 个随迁 spec 失败（缺 `## Purpose` 段），对照冻结旧仓库同样 6 个——搬家前既有，非搬家所致；本仓库自有 change 全部 strict 通过。修复 6 个 spec 另立 change

## 5. 服务器切换（需用户在场的窗口，每步有回退点）

- [x] 5.1 服务器落盘同款数据基线（卷列表 + 行数/节点数） **✅ 2026-09-03 采集**（ubuntu@43.167.170.20，旧栈 rag_coder 7 容器 + peco-platform 1 容器运行中）：卷恰四个 `rag_coder_*`（宿主共 5 卷；pgdata 63.4M / neo4jdata 1.5G / miniodata 2.6M / rabbitmqdata 268K）；PG `platform_users=3 users=8 projects=2 chat_sessions=6 chat_messages=29 index_jobs=9 understanding_reports=2 alembic=0010`；Neo4j 节点 4383 / 关系 7036；MinIO 8 个对象（repo-bundles / index-snapshots / reports）；公网 `/` 200、`/rag` 307→login、`/rag/api/health` 200、`/front` 200
- [x] 5.2 拉取新仓库；`docker compose config` 渲染检查卷名（up 之前，纸面上就能看出错） **✅ 2026-09-03**：`git clone main`（`ac00c53`）到 `~/peco`；`services/rag/.env` 与 `.env.production` 逐字节复制自旧目录，`deploy/.env` 软链；`docker compose config --format json` 24 项判定全过（项目名 peco、卷名恰四个 `rag_coder_*`、宿主端口仅 nginx 80/443 + 两个回环、restart 全 unless-stopped、AUTH_JWT_SECRET==NEXTAUTH_SECRET、MinIO/RabbitMQ 口令插值生效且非默认、nginx 四个挂载源存在、构建上下文正确）；三镜像后台预构建成功（`peco-backend`/`peco-worker` 1.81GB、`peco-platform` 337MB，日志零错误），旧栈全程在线
- [x] 5.3 down 旧栈 → 从 `deploy/` up 新栈 → 比对基线 → nginx 生效 **✅ 2026-09-03 05:17Z 执行**（脚本 `server-switch.sh`，全程 77s）：两旧栈 `compose down` 不带 `-v` → 四卷原地 → `~/peco` `up -d` → backend/platform 就绪用时 67s（公网中断约 1 分钟）。基线比对**全中**：四个 `rag_coder_*` 卷、PG 八项逐项相等（alembic 0010 未动）、Neo4j 4383/7036、MinIO 8 对象。宿主卷总数 6 而非基线 5：多出的是 Neo4j 镜像 `VOLUME /logs` 生成的匿名卷（新容器 `peco-neo4j-1` 一个；旧容器留下的 `7310d6c8…` 成孤儿，随 6.4 一起清），**四个数据卷零新增零改名**。nginx 起来即生效（`nginx -t` 通过）
- [x] 5.4 线上冒烟：`/`、`/login`（OAuth 回调）、`/rag` 全链路、MCP 端点 **✅ 2026-09-03**：`/` 200、`/login` 200、`/rag` 307→`/login?callbackUrl=%2Frag`、`/rag/api/health` 200、`/rag/api/projects` 401、`/rag/api/mcp` 401（未带 token）、`/front` 200、`http://` 与旧域 `heitu.wang` 均 301 → `https://baotao.wang`。OAuth 回调与登录态链路已由用户真人账号验证：登录后进入 `/rag` 项目列表、录入项目、触发索引均成功（2026-09-03）
- [x] 5.5 旧部署目录保留一周观察期，期间旧仓库只读 **观察期由用户于 2026-09-03 取消**：切换当天冒烟与日志全绿后，用户决定不留退路，已删服务器旧目录 `~/RAG_coder`（1.1G）与 `~/peco-platform`、旧镜像 `rag_coder-backend/worker/frontend` 与 `peco-platform-platform`、旧 Neo4j 匿名 `/logs` 卷（删前核对：新栈两份 env 与旧目录逐字节一致、无容器使用旧镜像）。回退路径自此不存在，回滚只能重建镜像。同日退役旧域 `heitu.wang`（nginx 块删、证书 `certbot delete`，见 server-notes）
- [x] 5.6 nginx 一致性确认（切换窗口内，轻量）：`nginx -T` 比对服务器生效配置与 `deploy/nginx-server.conf` 一致。预检时「线上或仍跑旧前端」的判断**有误已更正**：`8e0c946`（8-22）已把 `/rag` 归平台并附公网复测；`nginx-rag.conf` 是 M7 时代无消费者的死文件（见 migration-baseline §5.2） **✅ 2026-09-03**：`nginx -T` 显示 `conf.d/default.conf` + `projects/rag.conf` 两个文件生效，上游 `platform:3000` / `backend:8000`，`include /etc/nginx/projects/*.conf` 在位；容器内两份配置与仓库 `deploy/nginx/` 逐字节一致。宿主级唯一依赖 certbot 续期钩子已改为 `docker exec peco-nginx-1 nginx -s reload`
- [x] 5.7 MinIO 链路功能验证：切换后触发一次小型索引，确认 `rag-artifacts` 有对象落桶——基线时桶为空（0 对象），**空桶不作为「数据没丢」的证据** **✅ 2026-09-03**：切换后用户新录入项目并索引，MinIO 对象 8 → 19，新写入 `repo-bundles/<project>.bundle`（9 分片）与 `index-snapshots/<project>/<job>.json`，全部经新栈 worker 落桶——链路成立。同时观察到：用户删除了旧的两个项目并重新录入（新 ID，06:33/06:34Z），应用的删除是级联的（PG 外键 + Neo4j 子图），旧项目的 6 会话 / 29 消息 / 2 报告 / 整张图谱随之清空，MinIO 里旧 ID 的 bundle/快照/报告成为孤儿对象；新项目重索引卡在 `stage=embed`：硅基流动 402「余额不足」，属外部计费问题，与部署无关。**教训：切换基线应含 `pg_dump`，仅记行数无法在事后找回被删数据**。**2026-09-03 11:39 完整闭环**：修掉事件循环 bug 后 ColaMD 全程走通（11 分钟，`succeeded`/`stage=report`/100%）——clone → 310 chunks → 嵌入 35/35 批全新写入 → 5 个模块 / 5 个功能域 / 4 条业务流 → 报告落库；Neo4j 339 节点 353 关系（切换前是旧项目的 4383/7036，删项目后归零，这是新项目重建的图）；MinIO 23 对象（bundle + 快照 + 报告）。新栈的索引全链路自此有一次端到端成功记录
- [x] 5.8 服务器轮换 `SECRET_KEY`（泄露处置，2026-09-02）：改服务器 `services/rag/.env` → 重建 backend/worker → 有 git token 的私有项目重填 token。旧值曾随 `09e0c70` 上过公开仓库的 m16 分支，历史已改写（→`06e6905`）但 GitHub 孤儿 commit 仍可按 SHA 访问，**轮换才是止血**。本地已于 9-02 轮换完成 **✅ 核实：无需轮换**——服务器 `SECRET_KEY` 的 sha256 前缀 `3618475b63` ≠ 泄露值 `99fbe4755e`（泄露的是本地那份，线上从未用过），且 `projects.git_token_encrypted` 非空行数 = 0。服务器 `.env` 原样进新栈
- [x] 5.9 worker 日志 grep `AuthenticationError`：线上大概率仍用失效的旧 DeepSeek key（本地 9-02 已换 `deepseek-v4-pro`，旧 key 探测 401），同窗口换 key 并重建 worker **✅ 核实：无需换 key**——线上聊天/摘要走硅基流动（`CHAT_BASE_URL=api.siliconflow.cn`，`CHAT_MODEL=Qwen3-Coder-30B`，`SUMMARY_MODEL=DeepSeek-V4-Flash` 经硅基流动），worker 近 3000 行日志 `AuthenticationError` = 0。失效的 DeepSeek 直连 key 只在本地用过
- [x] 5.10 核查服务器 RabbitMQ / MinIO 是否仍是 compose 的 `:-` 默认口令（见 `deploy/compose/rag.yml`），是则换掉——MinIO 口令同时是存储层凭据，改后 `.env` 与 compose 两处要一致 **✅ 核实：已非默认**——`RABBITMQ_PASSWORD` 与 `MINIO_SECRET_KEY` 均为 32 位随机串（≠ compose `:-` 默认值），渲染检查再次确认插值进 rabbitmq / minio 服务

## 6. 收口

- [x] 6.1 老仓库 GitHub archive，README 首行加指针「已并入 peco-platform，历史见本仓库或新仓库 `services/rag`」 **✅ 2026-09-04**：README 首行加冻结横幅（指向 peco-platform 的 `services/rag/`，说明两边都有完整历史、锚点 `ceddadf`），提交 `9539b95` 推送后 `gh repo archive`，`isArchived=true` 已核实。仓库为 PRIVATE，转只读不影响任何公开引用
- [x] 6.2 CLAUDE.md「边界：后端不在这个仓库」章节反转重写（本地文件，随维护者）。实际改了五处而非一处：命令节补后端/编排、CI 表述、边界章节反转、鉴权的跨仓路径、构建部署的 external network 段
- [x] 6.3 README 架构段更新：三仓图 → 单仓多项目图；`openspec validate --strict` 收尾通过 **✅ 2026-09-04**：「后端不在本仓库」整段反转为单仓多项目（三行目录/工具链对照、两条链互不感知、平台不做 API 代理层、JWS 跨服务契约）；开发段补 `services/rag` 的 uv/pytest 与 `deploy/` 全栈命令，并写明基线零端口、开发端口只在 override 里、ports 是追加语义；`openspec validate --all --strict` 17/17 通过
- [x] 6.5 `deploy/DEPLOY.md` 顶部加过时横幅：全文描述的是 M7 宿主 nginx 部署方式，已被容器化 nginx 取代——一段声明 + 指向现行方式（migration-baseline 与第 5 组清单），**不重写正文**（内容变更超出本 change）
- [x] 6.4 删除 `../RAG_coder/frontend/` 磁盘残骸（1.1G；5.5 观察期结束后执行，自 1.3 移入） **✅ 2026-09-04**：删前三重核对——git 零跟踪（M12 的 `3b3acf5` 已从版本库删除）、目录内零源文件（只有 `.next` 545M + `node_modules` 536M）、源码早已在 `app/rag/`。老仓库 1.5G → 489M，宿主可用 71G。同时查明 1.4 悬置的未提交改动 `backend/app/api/projects.py` 纯属格式化（import 排序 + 行宽折行 + 注释空格），无逻辑变更，随仓库冻结一并作废
