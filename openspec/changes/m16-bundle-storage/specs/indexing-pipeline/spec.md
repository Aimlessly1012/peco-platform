## ADDED Requirements

### Requirement: 任务级临时工作区
索引任务 SHALL 在每任务独立的临时目录中工作，任务结束（无论成败）SHALL 清理该目录；本地磁盘 SHALL NOT 作为源码的跨任务持久存储。工作区来源优先级：MinIO bundle 恢复 + 远端 fetch 增量；bundle 不可用时直接 clone 远端（容错，不使任务失败）。

#### Scenario: 本地无任何副本时索引成功
- **WHEN** 本地磁盘无该项目任何数据（含 bundle 恢复失败的情形）
- **THEN** 任务经 clone 远端完成索引，且结束后本地不残留工作区

#### Scenario: bundle 恢复保全增量
- **WHEN** MinIO 有该项目 bundle 且远端有新 commit
- **THEN** 任务经 bundle 恢复 + fetch 增量后，增量索引的 git diff 判定照常生效

### Requirement: 无变化检测前移
任务开头 SHALL 以 git ls-remote 查询远端 HEAD；与基准 commit 一致时 SHALL 秒级返回，SHALL NOT 拉取 bundle 或 clone。

#### Scenario: 无变化不动存储
- **WHEN** 远端 HEAD 与 last_indexed_commit 相同
- **THEN** 任务秒级 succeeded，无 bundle 下载与本地工作区创建
