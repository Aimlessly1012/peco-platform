## 1. 部署脚本（先落地，此阶段仍手工执行，无自动触发）

- [x] 1.1 `deploy/scripts/deploy.sh`：读 `.last-deployed-sha` → `git pull --ff-only` → `git diff --name-only` 映射四类动作（后端 / 平台 / nginx / compose），无匹配则空跑退出
- [x] 1.2 后端分支必须同时 `build backend worker` 与 `up -d --force-recreate --no-deps backend worker`——只做其一是 server-notes 记过的坑
- [x] 1.3 nginx 分支必须 `--force-recreate`（单文件挂载换 inode），compose 分支执行 `up -d` 前先跑 `docker compose config -q` 做语法校验 + nginx 分支重建前先用一次性容器 `nginx -t`（脚本 v2 追加）
- [x] 1.4 构建前把现有 `peco-backend` / `peco-worker` / `peco-platform` 打 `:previous` 标签作为回滚点
- [x] 1.5 部署前统计 `index_jobs` 中 `status='running'` 行数并写入日志：本次中断 N 个任务，重跑将重复产生摘要成本（D5，不阻塞）
- [x] 1.6 构建前检查可用内存，低于阈值先 `docker builder prune -f`（当前缓存 12.8G 可回收）
- [x] 1.7 健康检查：平台首页与 `/rag/api/health` 均须 200；失败则 `:previous` 打回 `:latest`、重建容器、非零退出 **首版有 bug**：`curl --max-time` 会截断 `--retry`，backend 30 秒启动期内必判失败并触发无谓回滚（run 34076155336 撞上）；改为自写重试循环后于 run 34076458834 验证通过
- [x] 1.8 成功后写入 `.last-deployed-sha`；失败不写入，使下次部署仍从上一个成功点算 diff
- [x] 1.9 在服务器手工执行一次完整脚本（选一个只改文档的 commit，验证空跑分支），再选一个改后端的 commit 验证全流程 空跑（27 文件全文档，0.4s）与 nginx 分支（2.8s，容器内配置逐字节更新）均手工验证

## 2. 受限 deploy key（此阶段仍无 workflow，可随时中止）

- [x] 2.1 生成专用 ed25519 密钥对，命名区别于既有的人工运维密钥
- [x] 2.2 公钥写入服务器 `authorized_keys`，前缀 `command="/home/ubuntu/peco/deploy/scripts/deploy.sh",restrict`
- [x] 2.3 验证限权生效：用该密钥执行 `whoami` 等任意命令，确认实际运行的仍是部署脚本而非请求的命令 `whoami` 与 `cat .env` 均被强制命令替换为部署脚本，`.env` 零泄露；端口转发被 restrict 拒绝
- [x] 2.4 确认既有的人工运维密钥不受影响，仍可正常 SSH——这是脚本改坏时的唯一退路
- [x] 2.5 私钥与服务器地址写入仓库 Secrets 四个 secrets：SSH_KEY / HOST / USER / KNOWN_HOSTS（固定主机指纹），本地私钥已销毁

## 3. 部署 workflow

- [x] 3.1 `.github/workflows/deploy.yml`：`push: branches: [main]` 无 paths 过滤触发，显式不响应 `pull_request`
- [x] 3.2 等待 CI：查询本次 commit 的 check runs，全成功则继续、有失败则中止、进行中则轮询（上限暂定 15 分钟）、一个都没有则直接放行（D1）
- [x] 3.3 `concurrency: group: deploy-production, cancel-in-progress: false`——部署做到一半被取消会留下中间态
- [x] 3.4 SSH 执行部署，脚本的标准输出与退出码原样反映到 workflow 结果
- [x] 3.5 `workflow_dispatch` 入参提供「等待索引任务完成后再部署」的可选模式，供大仓库索引期间发布使用 标记经 SSH_ORIGINAL_COMMAND 进脚本（强制命令保留客户端命令但不执行），上限 30 分钟；`ea16f3b`

## 4. 端到端验证

- [x] 4.1 推一个纯文档 commit：确认 workflow 触发、脚本判定无需部署、不产生任何构建 run 34075997076：deploy.yml 自身的 push，无 CI、脚本判无需部署，端到端零构建跑通
- [ ] 4.2 推一个平台改动：确认只构建 platform、不碰后端两个镜像
- [x] 4.3 推一个后端改动：确认 backend 与 worker 都重建，容器内代码为新版 run 34076458834：等到 ci.yml 单测档通过 → build backend worker → 重建 → 健康检查 200，platform 未被无谓重建
- [x] 4.4 推一个 nginx 配置改动：确认容器内生效配置与仓库文件逐字节一致 手工执行验证：force-recreate 后容器内 rag.conf 含新注释，单文件挂载坑避开
- [ ] 4.5 故意推一个 CI 会失败的 commit：确认部署中止且线上版本未变
- [x] 4.6 故意让健康检查失败（临时改坏配置）：确认自动回滚到 `:previous` 且线上恢复可用 **意外验证**：run 34076155336 因健康检查 bug 判失败 → 自动切回 `:previous` → 线上四端点始终 200 → 基准未写
- [x] 4.7 连续推两个 commit：确认 diff 基准是上次成功部署点，不漏掉中间变更 df8abe3 → 5353a4a（失败不写基准）→ 9002388（diff 自动含前次变更，一并补上）

## 5. 文档与收口

- [x] 5.1 重写 `deploy/DEPLOY.md`：以统一栈形态为准，自动部署为主路径、手工部署为兜底，删除 M7 时代的过时正文与横幅 重写为统一栈形态：自动部署主路径、手工兜底、从零部署清单、迁移附录改为通用的换嵌入模型流程；旧文档的裸 curl 触发索引已不成立（接口需平台登录态），改为 UI 触发
- [x] 5.2 `deploy/server-notes/README.md` 补记：deploy key 的限权形式、脚本自举依赖（脚本改坏时怎么救）、rsync 相关内容已随 git clone 化失效 已补：自动部署机制、rsync 内容失效、deploy key 限权、自举依赖救法、一代回滚点、不阻塞任务的代价、首次后端部署撞的健康检查 bug
- [ ] 5.3 观察数次自动部署后的构建缓存增长，确定 1.6 的清理阈值是否合适（**基线 2026-09-07**：Build Cache 12.82G / 可回收 10.81G，磁盘可用 34G；两次后端构建后未增长，因改动全部缓存命中）
- [ ] 5.4 `openspec validate --all --strict` 全过，归档本 change
