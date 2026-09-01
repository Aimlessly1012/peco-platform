# indexing-pipeline — report 阶段（M3）

## MODIFIED Requirements

### Requirement: 任务阶段推进与统计
索引任务 SHALL 按 clone → parse → summarize → embed → graph → report 顺序推进并实时更新 stage/progress/stats；每阶段完成即持久化，任务成功后项目状态置 ready。stats SHALL 额外记录模块数、摘要新调用数与缓存命中数、CALLS_API 边数与 warning 数，以及报告生成情况（时序图成功/降级数）。

#### Scenario: 阶段推进可观测
- **WHEN** 任务从 parse 进入 summarize
- **THEN** 任务记录的 stage 变为 summarize，progress 相应推进

#### Scenario: 理解层统计可见
- **WHEN** 索引成功完成
- **THEN** stats 含 modules、summaries_new、summaries_cached、api_edges 等计数

#### Scenario: 报告阶段推进
- **WHEN** graph 阶段完成
- **THEN** 任务 stage 变为 report，报告生成完毕后任务 succeeded 且 stats 含 sequences_ok/sequences_fallback 计数
