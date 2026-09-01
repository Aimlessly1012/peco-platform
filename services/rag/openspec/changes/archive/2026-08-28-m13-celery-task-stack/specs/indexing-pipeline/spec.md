## ADDED Requirements

### Requirement: 重启恢复语义
索引任务 SHALL 在执行进程重启后自动恢复执行（经任务队列重投递），并利用增量语义快速跳过已完成部分；系统 SHALL NOT 将中断任务标记为 failed 后等待人工重新触发。

#### Scenario: 中断任务自动续跑
- **WHEN** 索引任务执行到 embed 阶段时执行进程重启
- **THEN** 任务自动重新执行，已入库的摘要与向量经缓存/增量判定快速跳过，最终 succeeded

#### Scenario: 前端无感知差异
- **WHEN** 任务因重启被重投递
- **THEN** 前端 SSE 收到的进度事件结构与正常执行一致，无需专门处理重启态
