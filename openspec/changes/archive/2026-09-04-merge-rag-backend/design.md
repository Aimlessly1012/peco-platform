## Context

三仓现状：peco-platform（Next 前端 + 平台 API，无 CI）、RAG_coder（FastAPI 后端 +
6 服务 compose + ci.yml + openspec 8 capability，前端已删只剩僵尸产物）、heitu-platform
（npm 包，**不参与本次合并**，`/front` 与它的关系保持 npm install 消费不变）。

关键实测事实：

- RAG_coder 是独立 git 仓库（GitHub remote），活跃开发中（m17），git 树顶层：
  `.claude .github backend deploy docs openspec` + 三个 compose 变体 + README
- 数据卷实名：`rag_coder_pgdata` / `rag_coder_neo4jdata` / `rag_coder_miniodata`
  （前缀来自**目录名**派生的 compose 项目名——这就是最大的坑）
- `data/repos`（110M）已 gitignore，是任务级临时区，**不需要搬**。
  **预检实测修正**：compose 注释称「M16 后主存储是 MinIO bundle」，但 `rag-artifacts` 桶
  实际为**空**（0 对象），而 `projects`=3、`index_jobs`=8——注释所述状态尚未成为现实。
  对迁移是好消息（MinIO 无数据可丢），但**空桶不能反向作为数据完整的证据**，
  MinIO 链路要靠切换后的功能验证（tasks 5.7）
- `RAG_coder/frontend/` 不在 git 树中，磁盘残骸 + 3300 端口进程（PID 48629，
  跑的是 `.next/standalone`，源码已不存在）
- Postgres 里 `platform_users`（平台写）与 M8 遗留 `users` 表共存——**数据拓扑不在本次范围**

## Goals / Non-Goals

**Goals:**

- RAG 后端成为本仓库 `services/rag/`，从新位置可独立构建、测试、部署
- 三个数据卷零搬运跨过迁移（Postgres 用户表、Neo4j 图谱、MinIO 源码包一行不丢）
- 一条 `docker compose up` 起全栈，external network 缝合消失
- openspec、CI、git 历史全部随迁，老仓库体面退役

**Non-Goals:**

- 不改任何运行时行为——API、鉴权语义、路由、SSE/MCP 链路逐字节不变
- 不做项目槽位化（注册表、nginx 按项目拆文件）——那是 platform-project-slots 的事
- 不动数据拓扑（`platform_users` 住在 ragcoder 库、M8 `users` 表清理）——阶段三另立
- 不删登录回退（`auth_jwt_secret` 为空退回密码登录）——行为改动，归 change C
- 不合并 heitu-platform

## Decisions

### D1：subtree 并入，不用拷贝重建

RAG 的文档与 openspec 里大量引用 commit 号（`d0cb7ea`、m 系列里程碑），拷贝进来这些引用
全部死掉，查历史要跳回 GitHub 归档仓库。`git subtree add` 让历史本地可 grep、blame 可用。
代价是并入 commit 的 diff 巨大——接受，它是一次性的，且 message 会写明来源仓库与 HEAD。

### D2：卷名固定在卷级，伞项目名自由

**这是全 change 唯一可能丢数据的地方。** compose 项目名默认取目录名，配置搬进 peco-platform
后项目名变化 → `up` 创建全新空卷 → 三个卷的数据「看起来消失」。

不采用「伞项目写死 `name: rag_coder`」——那是把第一个房客的名字刻在楼上，后续项目全住在
错误的命名空间里。采用**卷级显式命名**：

```yaml
volumes:
  pgdata:      { name: rag_coder_pgdata }
  neo4jdata:   { name: rag_coder_neo4jdata }
  miniodata:   { name: rag_coder_miniodata }
  rabbitmqdata: { name: rag_coder_rabbitmqdata }
```

伞项目叫 `peco`，数据原地不动。卷名里的 `rag_coder_` 前缀成为化石——接受，改卷名要
docker 层数据拷贝，收益是纯美观，不值。

### D3：纯拓扑纪律——一行行为变更都不带

m15 的教训直接适用：108 行无关格式化混进功能 commit，冲掉了 diff 的可读性。本 change 的
diff 天然巨大（subtree 并入），**更**不能夹带行为变更——出问题时必须能回答「是搬家搬坏的，
还是改坏的」。所以：路径修正（compose 里 `./backend` → `./services/rag`）属于拓扑，
启动校验、删回退属于行为，后者一律不进。

**边界澄清（预检发现后补）**：`deploy/nginx-rag.conf:54` 把 `/rag` 指向 `127.0.0.1:3300`
——那是无源码的僵尸前端，本 change 正在退役它。**指向退役中上游的路由不受 D3 保护**：
新拓扑里 3300 不存在，把 `/rag` 上游修正为 platform 服务是拓扑迁移的组成部分，不是
D3 禁止的行为变更。D3 保护的是 API、鉴权、业务代码的行为，不是「继续路由到被拆除的服务」。

（后记：上例经查历史被证明是**死文件里的死配置**——`8e0c946` 早已把 `/rag` 归平台，
该文件全仓无消费者。原则保留：真出现指向退役上游的活配置时照此处理；本案实际动作
只是死文件退役。另一个真实的 D3 边界案例见 tasks 3.8：`REPO_ROOT` 表达式的意图始终是
「仓库根」，搬家使它指错——**修复被搬家打断的语义属于拓扑修正**，即便它动的是测试代码。）

### D4：compose 用 include 拆分，为槽位化铺路但不越界

根 `deploy/docker-compose.yml` 只放 `include:` 列表与共享基础设施（db），RAG 六服务栈
一个文件 `deploy/compose/rag.yml`，平台一个 `platform.yml`。这一步做到「按项目一个文件」
即止；注册表、nginx conf.d 化、接入清单归 platform-project-slots。

### D5：服务器切换清单化，且必须有数据基线

切换的核心不是「起得来」，是「起来的是原来的数据」。清单强制顺序：
快照基线（`docker volume ls` + `platform_users` 行数 + Neo4j 节点数）→ down 旧 →
从新仓库 `docker compose config` 渲染检查卷名 → up → 对比基线 → 冒烟。
渲染检查放在 up 之前——卷名错了在纸面上就能看见，不用等数据消失才发现。

### D6：openspec 整体平移，不重命名

8 个 capability 目录原样并入根 `openspec/specs/`，`m17-test-baseline` 并入 `changes/` 继续。
`portfolio-platform`、`deployment` 等名字与本仓库新 capability 潜在的语义重叠**暂不处理**——
重命名会使 RAG 侧文档里的引用批量失效，churn 大于收益。合并后如需整理另立 change。

### D7：生产栈以 override 叠加统一栈（实施中发现的缺口，追加决策）

3.1 拆分伞文件后暴露：`prod.yml` 是**另一份完整定义**且不含 platform——开发栈统一了，
生产栈仍是两个 compose 项目靠 external network 缝合，Goals 的「一条 up 起全栈」在真正
要紧的环境里不成立。

三个方向：prod 也 include 化（文件翻倍，两份完整定义继续互相漂移——正是本项目反复对抗的
腐烂模式）；**prod 改为真 override**（采纳：服务定义单一来源，prod 只写差异，platform 随
伞文件自动进入）；不动（违背本 change 自己的 Goals，否决）。

它是编排结构调整，仍在「拓扑」范畴——本 change 的主业就是编排归属，D3 禁的是运行时行为
变更，不是编排文件的组织方式。

已知陷阱：compose 对 list 字段是**合并追加**，override 删不掉 base 里的端口映射。

**落地修正（3.9 实施后）**：v1 措辞「以开发栈为 base、override 去端口」因此不成立；
`!reset` 需 Compose 2.24+，服务器版本未知——赌输的代价是 Postgres/Neo4j 挂公网，不赌。
最终采用**倒置**：基线（伞 + `compose/*.yml`）本身即生产安全形态（无宿主端口、无 restart），
开发端口移入 `docker-compose.override.yml` 靠默认发现生效，显式 `-f` 的生产组合不加载它。
方向判据是**默认状态必须落在安全一侧**：忘记叠覆盖层，最坏是本地连不上；反向则是库挂公网
——与 `lib/auth.ts`「DB 失联降级为拒绝」同一取向。

验收用 render-diff（改写前后各渲染一次生产 `config`，diff 只允许意图内差异），它抓到了
v1 覆盖层漏掉的 4 项生产配置（`ROOT_PATH`、neo4j 内存调优、3 个 `mem_limit`）——「渲染
通过」发现不了这类丢失。附带方法论教训（同 change 内被踩两次后升为动作）：**diff 基线必须与被比对象在相同
外部条件下产生**——首次因 `.env` 存在性混入数十行噪声；二次因并发会话在对照窗口内改了
`server.yml` 而混入无关挂载行。自此「对照窗口内 md5 确认无关文件未变」是 render-diff 的
组成步骤，不是运气。

## Risks / Trade-offs

**R1：卷名渲染错误 = 数据级事故** → D2 双保险：卷级显式 name + 切换清单的「up 前渲染检查、
up 后基线比对」。基线数字（行数、节点数）在预检阶段就落盘，不靠临场记忆。

**R2：迁移窗口内 RAG 侧继续开发产生分叉** → 后端会话自己就是 RAG 的开发者：subtree 并入
前冻结旧仓库推送，并入后所有 RAG 开发在新仓库进行。窗口由执行顺序保证，不靠约定。

**R3：构建上下文互染** → 平台 Dockerfile 是 `COPY . .`，合并后会把 `services/` 拷进 Next
镜像（肥而不坏）；rag 的构建上下文路径全变。两侧 `.dockerignore` 与 compose `build.context`
在本地验证阶段用「镜像能构建 + 体积无异常膨胀」验收。

**R4：服务器切换是唯一需要停机的步骤** → 个人站可停，但窗口需用户在场；清单里每步都有
回退点（旧目录保留 N 天，down 的旧栈随时能 up 回去）。

**R5：subtree 后局部路径引用残留** → `grep -rn "\.\./RAG_coder\|\./backend"` 作为收口
检查项，宁可多跑一次全文搜索。

## Migration Plan

见 tasks 的分组顺序：预检（无破坏）→ 并入（git 操作，独占工作区）→ 编排统一 → 本地全栈
验证 → 服务器切换（用户窗口）→ 收口。预检组可立即执行且完全可逆；subtree 组开始前需要
分支基线决策（见 Open Questions）。

## Open Questions

- **分支基线**：`m15-heitu-field-reference` 已完成未合并。subtree 的巨型 diff 叠在未合并
  分支上会让两个 change 的历史纠缠。建议：先把 m15 合回 main，本 change 从 main 开新分支。
  等用户决定。
- ~~服务器 `/rag` 实际上游~~ **已解决，无需用户核实**：服务器生效的是
  `deploy/nginx-server.conf`（compose 挂载），`8e0c946`（8-22）已把 `/rag` 归平台并附
  公网复测记录；`nginx-rag.conf` 是 M7 时代无消费者的死文件，随 3.5 退役。5.6 降级为
  切换窗口内的轻量一致性确认。此更正本身是 D1 选 subtree 的第一次收益兑现——
  错误结论正是靠并入后本地可查的历史纠正的，拷贝重建拿不到这条 commit。
- **老仓库归档时点**：服务器切换验证通过后立即归档，还是保留双活一段时间？建议切换后
  保留一周再归档，观察期内旧仓库只读不写。
