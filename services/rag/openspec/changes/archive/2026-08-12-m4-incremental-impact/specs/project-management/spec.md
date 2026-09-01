# project-management — 索引模式参数（M4）

## MODIFIED Requirements

### Requirement: 触发索引任务
系统 SHALL 提供 `POST /projects/{id}/index` 触发索引，支持查询参数 `mode=auto|full`（默认 auto，语义见 indexing-pipeline「重建与增量语义」）；同一项目已存在 running 任务时 MUST 返回 409；任务创建后异步执行，接口立即返回任务 id，任务记录的 kind SHALL 反映实际执行模式（full/incremental）。

#### Scenario: 重复触发被拒绝
- **WHEN** 项目已有 running 索引任务，再次调用触发接口
- **THEN** 返回 409，且不创建新任务

#### Scenario: 失败后重试
- **WHEN** 项目上次索引任务为 failed，用户再次触发索引
- **THEN** 创建新任务并执行（auto 模式按增量判定规则决定实际路径）

#### Scenario: 强制全量
- **WHEN** 以 mode=full 触发索引
- **THEN** 执行全量重建，任务 kind 为 full
