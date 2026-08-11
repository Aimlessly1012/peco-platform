# indexing-pipeline — 增量重索引与可观测性（M4）

## REMOVED Requirements

### Requirement: 全量重建语义（M1）
**Reason**: M4 起重新索引默认 auto（可增量），全量重建降级为其中一种模式，语义由新需求「重建与增量语义」完整覆盖
**Migration**: 强制全量的原行为通过 `POST /projects/{id}/index?mode=full` 保留

## ADDED Requirements

### Requirement: 重建与增量语义
重新索引 SHALL 支持 auto 与 full 两种模式（默认 auto）。auto 模式下，若项目存在 last_indexed_commit 且本地副本可用，SHALL 以 `git diff --name-status` 计算变更集执行增量：无变更时任务 SHALL 在秒级成功返回（stats 标 no_changes，不改动图与报告）；有变更时仅对新增/修改文件重解析、重摘要、重嵌入，删除/改名文件的 File 与 DEFINES 子图删除，未变更文件的节点与向量 MUST 保持不动；结构边（HAS_MODULE/CONTAINS/IMPORTS/CALLS_API）SHALL 全量重连；路由解析与归属全局重算（未变更文件的 imports 从图读回，不再读盘解析）。auto 判定不满足时 SHALL 回退全量并在 stats 记录 fallback_full_reason。last_indexed_commit MUST 仅在任务成功后更新。

#### Scenario: 无变更秒级返回
- **WHEN** 对已就绪项目触发 auto 索引且远端无新提交
- **THEN** 任务在秒级 succeeded，stats 含 no_changes=true，图与报告未发生写操作

#### Scenario: 增量与全量图等价
- **WHEN** 对同一变更集分别执行增量索引与强制全量索引
- **THEN** 两者产出的图等价（节点集、边集、内容 hash 一致），且增量路径中未变更文件保留原 embedding

#### Scenario: 删除文件无残留
- **WHEN** 变更集中包含删除的文件
- **THEN** 增量完成后图中不存在该文件的 File/Chunk 节点及其任何边

#### Scenario: 回退全量可解释
- **WHEN** 项目无 last_indexed_commit（或本地副本缺失）时触发 auto 索引
- **THEN** 执行全量流程，stats 含 fallback_full_reason

### Requirement: 阶段内子进度
summarize 阶段 SHALL 按已完成文件数、embed 阶段 SHALL 按已完成批次数在各自进度区间内连续推进 progress（节流：每 5% 或 ≥2 秒），stats SHALL 含 summarize_done/summarize_total 与 embed_done/embed_total。

#### Scenario: 大仓库进度连续可见
- **WHEN** 千文件级仓库处于 summarize 阶段
- **THEN** progress 在 25-55 区间随完成数持续增长，不长时间停驻单一数值

### Requirement: 模型调用超时
LLM 摘要与嵌入的单次调用 MUST 设置显式超时（环境变量可配，默认摘要 60s / 嵌入 30s），超时视为该次调用失败进入既有退避与降级路径。

#### Scenario: 单次调用挂起不阻塞管道
- **WHEN** 某次摘要调用超过超时上限无响应
- **THEN** 该调用被中止并按退避重试，最终失败则降级占位，管道继续
