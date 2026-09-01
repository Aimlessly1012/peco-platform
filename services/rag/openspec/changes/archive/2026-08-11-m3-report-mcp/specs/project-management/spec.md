# project-management — 六阶段进度与详情页（M3）

## MODIFIED Requirements

### Requirement: 索引任务进度查询
系统 SHALL 提供任务查询接口，返回任务的 kind、status、stage（clone/parse/summarize/embed/graph/report）、progress(0-100)、stats（文件数/块数/跳过数/模块数/摘要计数/报告计数）、error_text；前端 SHALL 以轮询（约 2s）刷新进度，进度条按六阶段展示（拉取代码/解析分块/生成摘要/向量化/写入图谱/生成报告）。

#### Scenario: 查询运行中任务
- **WHEN** 查询 running 任务
- **THEN** 返回当前 stage 与 progress，stats 随处理推进更新

#### Scenario: 查询失败任务
- **WHEN** 查询 failed 任务
- **THEN** 返回 error_text 供前端展示失败原因

#### Scenario: 报告阶段可见
- **WHEN** 任务处于 report 阶段时查询
- **THEN** 返回 stage=report，前端进度条显示「生成报告」

## ADDED Requirements

### Requirement: 项目详情页
前端 SHALL 提供项目详情页 `/projects/{id}`，含三页签：项目理解、功能地图（行为契约见 understanding-report 能力）、索引记录（历次任务列表：kind/status/stage/耗时/stats 展开/error_text）。项目列表卡片 SHALL 提供详情页入口。

#### Scenario: 查看索引记录
- **WHEN** 用户打开详情页「索引记录」页签
- **THEN** 按时间倒序看到历次任务的状态、阶段、耗时与统计，失败任务可见错误信息
