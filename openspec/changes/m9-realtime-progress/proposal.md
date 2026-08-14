# M9: 实时进度与聊天阶段展示（SSE 推送替代轮询）

## Why

两个体验痛点（用户提出）：

1. **索引进度靠前端 2 秒轮询**：录入项目后页面反复打 `/jobs/latest`，进度跳变不平滑，服务器空转请求多
2. **聊天等待期是黑盒**：首答 15-30 秒里用户只看到 loading 动画 + 计时文案（F7 是纯前端猜的），不知道系统在干嘛

## 协议决策：SSE，不引入 WebSocket

用户最初问"可以换 WS 吗"。结论：这两个需求都是**服务器→客户端单向推送**，SSE 完全覆盖；WS 的双向能力用不上，却要重做鉴权（httpOnly cookie 在 WS 握手的验证）、重连状态机、Nginx upgrade 配置，并重踩代理兼容坑。聊天 SSE 链路的全部坑（缓冲/分隔符/超时/心跳）已在 M6/M7 趟平，进度推送直接复用同一套基建。

## What Changes

| # | 变更 | 说明 |
|---|------|------|
| 1 | 索引进度 SSE：`GET /projects/{id}/progress` | 进程内事件订阅（pipeline 的 on_progress 钩子发内存 broker），首连推快照、变化推增量、任务结束推 done 关流；前端轮询下线（保留为 SSE 失败的降级路径） |
| 2 | 聊天阶段事件：token 流前多几个 `event: stage` | chat.py 把 LangGraph astream_events 的节点开始信号（rewrite / classify / retrieve / generate）映射成 stage 事件，**workflow 零改动** |
| 3 | 前端进度条接流 | 项目详情页 StageBar / 列表页状态徽章由 SSE 驱动，平滑更新 |
| 4 | 聊天 loading 换真实阶段 | F7 的计时文案升级为「改写问题 → 检索代码 → 生成回答」实时阶段展示 |
| 5 | （顺带提速）rewrite + classify 合并为单次 LLM 调用 | 首答省一次推理型模型的往返（实测每次 3-10 秒） |

## 不做什么

- 不引入 WebSocket、不加消息队列/Redis——单 worker 进程内存 broker 足够（DEPLOY.md 注明多 worker 部署时进度流需换实现）
- 索引进度不做历史回放（断线重连拿当前快照即可）

## Capabilities

- `indexing-pipeline`（MODIFIED）：进度实时流
- `code-chat`（MODIFIED）：阶段事件 + 前置调用合并
