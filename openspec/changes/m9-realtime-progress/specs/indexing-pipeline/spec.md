# indexing-pipeline — 索引进度实时流（M9）

## MODIFIED Requirements

### Requirement: 索引进度反馈
索引任务进度除节流写库外 SHALL 经进程内事件源实时发布；系统 SHALL 提供 `GET /projects/{id}/progress`（SSE，登录态）：连接时推送当前任务快照，此后推送增量进度事件（stage/progress/stats/status），任务到达终态（succeeded/failed）推送后关闭流；无运行中任务时直接关闭。前端 SHALL 以 SSE 订阅驱动进度展示，轮询仅作为 SSE 失败的降级路径。

#### Scenario: 录入项目后进度实时推送
- **WHEN** 用户录入项目触发索引并停留在详情页
- **THEN** 进度条随 SSE 事件平滑推进（无周期性 /jobs/latest 轮询请求），任务完成后流关闭且页面刷新报告

#### Scenario: 断线重连拿到快照
- **WHEN** 进度流连接中断后 EventSource 自动重连
- **THEN** 重连首帧为当前任务快照，进度不回退不错乱
