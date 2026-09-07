# push 到 main 后自动部署

## Why

当前从代码到线上全靠手动：本地 push、SSH 上服务器、`git pull`、按改动类型决定 build 哪些镜像、重建对应容器、再手工验一次健康检查。这条链有三个反复出现的失效点：

- **漏 build worker**。`backend` 与 `worker` 共用 `services/rag` 构建上下文但是两个独立镜像，只 `build backend` 的话 worker 会静默跑旧代码，`up -d` 不给任何提示。server-notes 里为此单独记了一条坑。
- **漏重建 nginx**。nginx 配置是单文件 bind mount，`git pull` 换掉 inode 后容器里挂的仍是旧文件，不 `--force-recreate` 等于没改。
- **CI 绿不绿全靠自觉**。push 之后没有任何机制阻止部署一个测试挂掉的 commit。

这些都是"记得就对、忘了就错"的步骤，正是应该交给机器的部分。

`deploy/DEPLOY.md` 顶部标着过时横幅（描述的是 M7 宿主 nginx 时代），server-notes 里的 rsync 同步方式在 M16 换成 git clone 后也已失效。当前这套流程只存在于口口相传里，仓库中没有可执行的记载。

## What Changes

- **新增 `.github/workflows/deploy.yml`**：push 到 main 后触发，等待该 commit 的相关 CI 检查全部通过，再经 SSH 在服务器执行部署。
- **新增服务器端部署脚本 `deploy/scripts/deploy.sh`**：按本次变更路径决定构建与重建范围，而不是每次全量重建。变更映射为四类——后端代码、平台代码、nginx 配置、compose 文件，纯文档改动不触发任何部署动作。
- **新增专用 deploy key**：生成独立密钥对，公钥写入服务器 `authorized_keys` 并以 `command=` 与 `restrict` 限制为只能执行部署脚本，私钥存入仓库 Secrets。此前那把 `github-actions-deploy` 因无工作流引用已于 2026-09-03 删除，本次是重新建立且收窄权限。
- **部署后健康检查与自动回滚**：验证平台首页与 `/rag/api/health`，失败则切回上一版镜像标签并重建。
- **索引任务冲突记账**：部署前统计运行中的索引任务数并显式记入部署日志。按决策不阻塞部署，但被中断任务导致的摘要重烧成本必须可见。
- **重写 `deploy/DEPLOY.md`**：以当前统一栈形态为准，覆盖自动部署路径与手动兜底路径。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `deployment`: 新增持续部署的行为约定——部署 SHALL 由 main 分支的 push 触发且以相关 CI 通过为前置条件；构建与重建范围 SHALL 由变更路径决定；部署凭据 SHALL 限权到只能执行部署脚本；部署后 SHALL 做健康检查，失败 SHALL 自动回滚到上一版镜像。

## Impact

- **新增文件**：`.github/workflows/deploy.yml`、`deploy/scripts/deploy.sh`。
- **改写文件**：`deploy/DEPLOY.md`（正文已过时）、`deploy/server-notes/README.md`（补自动部署与密钥限权说明）。
- **服务器**：`~ubuntu/.ssh/authorized_keys` 增加一把受限 deploy key；`~/peco` 需能被该 key 对应的强制命令操作。
- **GitHub**：仓库 Secrets 增加部署私钥与服务器地址。仓库为 public，需确保部署 workflow 不在 `pull_request` 事件上触发——fork 的 PR 虽拿不到 Secrets，但显式排除比依赖默认行为可靠。
- **不改动**：两个既有 CI workflow 的触发与 paths 配置保持原样，部署 workflow 单独判断 CI 结果。
