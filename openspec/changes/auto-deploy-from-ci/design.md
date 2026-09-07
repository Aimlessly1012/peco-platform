## Context

服务器 `~/peco` 是 main 分支的 git clone（M16 起，此前是 rsync 副本）。三个自建镜像与它们的构建上下文：

```
platform  ← 仓库根          337 MB
backend   ← services/rag  1.81 GB   ┐ 同一构建上下文
worker    ← services/rag  1.81 GB   ┘ 但 compose 视为两个独立镜像
```

两个既有 CI workflow 各带 paths 过滤，**留下一片盲区**：

| 改动路径 | ci.yml | ci-platform.yml | 需要部署 |
|---|---|---|---|
| `services/rag/**` | 触发 | — | backend + worker |
| `app/` `lib/` `components/` … | — | 触发 | platform |
| `deploy/nginx/**` | — | — | **nginx（但没有 CI 触发）** |
| `deploy/*.yml` | — | — | **compose 生效（同样无 CI）** |
| `openspec/` `*.md` | — | — | 不需要 |

这决定了部署 workflow 不能简单地挂在两个 CI 的下游：改 nginx 配置时两个 CI 都不跑，`workflow_run` 永远等不到。

资源约束仍然成立：3.6G 内存、可用约 1.37G，构建后端镜像时 load 到 4.3；构建缓存已积到 12.8G。

## Goals / Non-Goals

**Goals:**

- push 到 main 后无需人工介入即可上线，且只在相关 CI 通过时才部署。
- 构建与重建范围由变更路径决定，不做无谓的全量重建——一次后端全量构建要几分钟且吃满这台小机器。
- 把三个"记得就对、忘了就错"的步骤（build worker、重建 nginx、看 CI）固化成脚本。
- 部署失败能自动回到上一个可用版本，而不是留下一个半死的线上。

**Non-Goals:**

- 不把构建挪到 GitHub 的机器上（镜像推 registry 那条路）。收益明确但改造大，留作后续演进。
- 不做多环境（staging/prod）。只有一台服务器。
- 不做蓝绿或滚动发布。单机单实例，重建期间有秒级中断，可接受。
- 不阻塞正在运行的索引任务（见 D5，这是用户明确选定的取舍）。

## Decisions

### D1：deploy workflow 由 push 触发并自行等待 CI，而不是挂在 CI 下游

`workflow_run` 是常规做法，但它在本仓库有硬伤：`deploy/nginx/**` 与 `deploy/*.yml` 的改动不触发任何 CI，用下游模式会导致这类改动永远不部署——**而它恰恰是最需要自动化的那类**（nginx 单文件挂载的坑就出在这里）。

因此 deploy workflow 用 `push: branches: [main]` 无 paths 过滤地触发，第一步查询该 commit 的 check runs：

```
本次 commit 的 check runs
  ├─ 存在且全部成功 → 部署
  ├─ 存在且有失败   → 中止，不部署
  ├─ 仍在运行       → 轮询等待（有上限）
  └─ 一个都没有     → 说明改的是 deploy/ 或文档，直接放行
```

"一个都没有就放行"是有意为之：这类改动本就没有对应测试，卡住它等于让盲区继续存在。

**替代方案**：给两个 CI 的 paths 补上 `deploy/**`。否决——那会让改 nginx 配置去跑一遍 Python 测试和 Next 构建，纯属浪费，且没有任何东西在测 nginx 配置。

### D2：变更检测在服务器端做，用 git diff 而非 workflow 的路径过滤

部署脚本拿到"上一次部署的 commit"与"本次 commit"，`git diff --name-only` 出变更文件，映射到四类动作：

```
services/rag/**                          → build backend worker; recreate backend worker
app/|lib/|components/|scripts/|*.ts|...  → build platform;        recreate platform
deploy/nginx/**                          →                        recreate nginx
deploy/*.yml | deploy/compose/**         →                        up -d（compose 自行 diff）
其余                                      → 无动作
```

放在服务器端而不是 workflow 里，是因为**上一次部署的真实状态只有服务器知道**。若上次部署失败或被跳过，workflow 侧按 `github.event.before` 算出的 diff 会漏掉中间的变更。服务器落盘一个 `.last-deployed-sha`，diff 以它为准，天然覆盖"连续几次 push 只成功部署了最后一次"的情形。

首次运行或 sha 文件缺失时退化为全量部署。

### D3：deploy key 用强制命令限权，而非一把可登录的普通密钥

私钥存在 GitHub Secrets 就意味着"GitHub 一旦被攻破或配置写错，攻击者拿到服务器 shell"。用 `authorized_keys` 的强制命令把它钉死在部署脚本上：

```
command="/home/ubuntu/peco/deploy/scripts/deploy.sh",restrict ssh-ed25519 AAAA... deploy-from-ci
```

`restrict` 关掉端口转发、agent 转发、X11 与 TTY 分配。这样即使私钥泄露，能做的也只是触发一次部署——而部署本身只拉 main 分支的代码，攻击者无法借此执行任意命令。

**代价**：脚本路径写死在 authorized_keys 里，脚本自身的更新不经过这条通道（它由 `git pull` 更新，而 pull 是脚本自己执行的第一步）。这形成一个小的自举依赖：脚本改坏了，下一次部署会用改坏的版本。缓解是脚本改动必须本地手工验一次再合。

**替代方案**：不限权，给普通 SSH 访问。否决——public 仓库的部署凭据要按"可能泄露"来设计。

### D4：镜像标签做回滚点，健康检查失败自动切回

构建新镜像前，把当前 `peco-backend:latest` 等打上 `:previous` 标签。部署后依次检查：

```
平台首页          https://baotao.wang/          期望 200
后端健康检查      https://baotao.wang/rag/api/health   期望 200
```

任一失败：把 `:previous` 重新打回 `:latest` 并重建对应容器，然后以非零码退出让 workflow 变红。

**为什么不用 compose 的 profile 或多版本共存**：单机单实例、内存只剩 1.3G，跑两份后端镜像的容器不现实。标签切换是这台机器上唯一可行的回滚形态。

**已知局限**：`:previous` 只保留一代。连续两次坏部署会失去回滚点。可接受——第二次坏部署时人已经该介入了。

### D5：不阻塞运行中的索引任务，但把代价记入日志

用户选定：部署即执行，不等待任务完成。Celery 的 `acks_late` 保证任务不丢，会重新入队续跑。

代价是真实的：被中断的任务重跑时，若上一轮尚未走到 graph 阶段，摘要结果没有落盘、缓存为空，那部分 LLM 调用要全价重烧。2026-09-04 的 onyx 索引因 OOM 触发同一机制，5938 次调用里约 2726 次是重跑产生的。

因此部署脚本 SHALL 在动手前统计 `index_jobs` 中 `status='running'` 的行数，并在日志中显式记录本次部署中断了多少个任务。**不改变行为，只让浪费可见**——否则这笔钱会以"账单莫名偏高"的形式沉默地流失。

同时提供一个手动逃生口：workflow 的 `workflow_dispatch` 入参可选择"等待任务完成"，供大仓库索引期间需要发布时使用。

### D6：并发与幂等

workflow 用 `concurrency: group: deploy-production, cancel-in-progress: false`。不取消进行中的部署——部署做到一半被杀会留下容器与镜像标签不一致的中间态；排队等前一次做完更安全。

脚本本身幂等：重复对同一 commit 执行只是重新构建并重建，结果一致。

## Risks / Trade-offs

**[部署凭据存在 GitHub]** → 用 D3 的强制命令把爆炸半径压到"能触发部署"。残余风险是攻击者可反复触发部署制造服务抖动，可接受。

**[脚本自举依赖]** → 部署脚本改坏后，下一次部署会用坏版本。缓解：脚本改动本地先手工跑一次；authorized_keys 里保留原有的人工运维密钥，脚本坏掉时仍能 SSH 进去修。

**[构建期资源紧张]** → 后端镜像构建期间可用内存降到 1.2G 上下，若同时有索引任务在跑，worker 可能被 OOM 杀掉。这与 D5 的取舍叠加会放大浪费。缓解：脚本在构建前记录内存水位，低于阈值时先 `docker builder prune` 释放缓存。

**[自动部署掩盖 CI 盲区]** → `deploy/` 下的改动没有任何自动测试，D1 让它们直接放行。nginx 配置写错会在部署后由健康检查发现并回滚，但 compose 配置错误可能表现得更隐蔽。缓解：脚本在 `up -d` 前先跑一次 `docker compose config -q` 做语法校验。

**[一代回滚点不够]** → 见 D4，接受。

## Migration Plan

见 tasks.md。顺序为：先在服务器建立受限密钥并手工验证强制命令生效（此时尚无 workflow，无风险）→ 落地部署脚本并手工执行一次全流程 → 最后接上 workflow 自动触发。

每一步都保留手动部署路径，任何环节失败都可以回到当前的手工流程。

**回滚整个改动**：删除 workflow 文件、从 `authorized_keys` 移除 deploy key 即可，服务器状态不受影响。

## Open Questions

- **CI 等待的超时上限**：集成档要起 Neo4j 与 MinIO，实测耗时需要确认后再定轮询上限，暂按 15 分钟。
- **是否给部署结果加通知**：失败时目前只体现在 workflow 变红。是否要接一个通知渠道，取决于是否会盯 GitHub 的邮件。
- **构建缓存清理策略**：12.8G 可回收缓存该定期清还是按水位清，需要观察几次自动部署后的增长速度再定。
