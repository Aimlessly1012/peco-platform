# project-management — 进度阶段扩展（M2）

## MODIFIED Requirements

### Requirement: 索引任务进度查询
系统 SHALL 提供任务查询接口，返回任务的 kind、status、stage（clone/parse/summarize/embed/graph）、progress(0-100)、stats（文件数/块数/跳过数/模块数/摘要计数）、error_text；前端 SHALL 以轮询（约 2s）刷新进度，进度条按五阶段展示（拉取代码/解析分块/生成摘要/向量化/写入图谱）。

#### Scenario: 查询运行中任务
- **WHEN** 查询 running 任务
- **THEN** 返回当前 stage 与 progress，stats 随处理推进更新

#### Scenario: 查询失败任务
- **WHEN** 查询 failed 任务
- **THEN** 返回 error_text 供前端展示失败原因

#### Scenario: 摘要阶段可见
- **WHEN** 任务处于 summarize 阶段时查询
- **THEN** 返回 stage=summarize，前端进度条显示「生成摘要」
