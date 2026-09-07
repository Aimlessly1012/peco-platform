## ADDED Requirements

### Requirement: main 分支自动部署
向 main 分支的 push SHALL 自动触发生产部署，且部署 MUST 以该 commit 的相关 CI 检查全部通过为前置条件。检查仍在进行时 SHALL 等待至设定上限；存在失败检查时 SHALL 中止部署；该 commit 未触发任何检查时（例如仅改动 `deploy/` 或文档）SHALL 放行——这类路径不在既有 CI 的 paths 过滤内，卡住它们等同于让部署盲区继续存在。部署 SHALL NOT 由 `pull_request` 事件触发。

#### Scenario: CI 通过后自动上线
- **WHEN** 向 main 推送改动了 `services/rag/**` 的 commit 且其 CI 检查全部成功
- **THEN** 自动在服务器完成对应镜像构建与容器重建，无需人工登录服务器

#### Scenario: CI 失败时不部署
- **WHEN** 该 commit 的任一 CI 检查失败
- **THEN** 部署中止且线上保持原版本，工作流以失败状态结束

#### Scenario: 无检查的路径直接放行
- **WHEN** 推送仅改动 `deploy/nginx/**` 或文档，未触发任何 CI 检查
- **THEN** 部署照常执行，不因等不到检查结果而挂起

### Requirement: 按变更路径决定部署范围
部署 SHALL 依据「上次成功部署的 commit」与当前 commit 之间的文件差异决定构建与重建范围，MUST NOT 每次全量重建。基准 commit SHALL 由服务器侧持久记录，以覆盖连续多次推送只有最后一次成功部署的情形；记录缺失时 SHALL 退化为全量部署。后端代码变更 SHALL 同时重建 backend 与 worker 两个镜像——二者共用构建上下文但属于独立镜像，只构建其一会使 worker 静默运行旧代码。nginx 配置变更 SHALL 强制重建 nginx 容器——配置以单文件挂载，文件替换后 inode 变化，不重建则容器内仍是旧配置。

#### Scenario: 后端改动同时更新两个镜像
- **WHEN** 本次变更包含 `services/rag/**`
- **THEN** backend 与 worker 两个镜像均被重新构建，且两个容器均被重建

#### Scenario: nginx 配置改动强制重建容器
- **WHEN** 本次变更包含 `deploy/nginx/**`
- **THEN** nginx 容器被强制重建，容器内生效配置与仓库文件一致

#### Scenario: 纯文档改动不触发重建
- **WHEN** 本次变更仅涉及 `openspec/` 或 Markdown 文件
- **THEN** 不执行任何镜像构建与容器重建

### Requirement: 部署凭据限权
用于自动部署的 SSH 凭据 SHALL 在服务器侧以强制命令绑定到部署脚本，并禁用端口转发、agent 转发与 TTY 分配，MUST NOT 具备任意命令执行能力。仓库为公开仓库，该凭据 SHALL 按可能泄露来设计权限边界。

#### Scenario: 凭据无法执行部署以外的命令
- **WHEN** 持有部署私钥的一方尝试以该密钥执行任意远程命令
- **THEN** 服务器仅执行既定的部署脚本，请求的命令不被执行

### Requirement: 部署后健康检查与回滚
部署 SHALL 在完成后验证平台首页与后端健康检查端点，任一不可用时 SHALL 自动将镜像切回上一版本并重建对应容器，随后以失败状态结束。构建新镜像前 SHALL 保留当前镜像的上一版标签作为回滚点。

#### Scenario: 健康检查失败自动回滚
- **WHEN** 部署完成后后端健康检查端点返回非 200
- **THEN** 相关容器以上一版镜像重建，线上恢复到部署前的可用状态，工作流报告失败

#### Scenario: 部署中断的索引任务可见
- **WHEN** 部署执行时存在运行中的索引任务
- **THEN** 部署日志显式记录被中断的任务数量，说明其将由队列重投递且重跑会重复产生摘要调用成本
