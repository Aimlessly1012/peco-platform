# M9 设计

## D1 进度事件源（进程内 broker）

```
pipeline on_progress（已有节流写库钩子）
      └→ progress_broker.publish(project_id, {stage, progress, stats, status})
GET /projects/{id}/progress  (SSE, require_user)
      └→ 首连：推当前快照（读 DB 最新 job）
         订阅：broker 增量事件原样推
         终态：status ∈ {succeeded, failed} 推完即关流
```

- broker：`dict[project_id, set[asyncio.Queue]]`，publish 非阻塞（队列满丢旧事件，进度流丢帧无害）
- 心跳：沿用 sse-starlette 15s ping（Nginx 超时链路已配好）
- 无运行任务时：推一条 `{status: "idle"}` 后保持连接（用户可能马上触发索引）或直接关流——**取关流**，前端触发索引后再连
- 多 worker 失效问题：uvicorn 单 worker（现状）内存 broker 正确；DEPLOY.md 注明扩 worker 需换 Redis pub/sub

## D2 聊天阶段事件（chat.py 纯映射）

astream_events 已在消费事件流（tags=["answer"] 过滤 token）。追加：`on_chain_start` 且节点名 ∈ {rewrite, classify, retrieve, generate} 时发：

```
event: stage
data: {"stage": "rewrite" | "classify" | "retrieve" | "generate"}
```

- workflow.py 不动；SSE 事件序：stage* → token* → citations → done
- 前端文案映射：rewrite/classify →「正在理解问题…」、retrieve →「正在检索代码…」、generate →「正在生成回答…」；未知 stage 忽略（向前兼容）

## D3 rewrite + classify 合并（顺带提速）

现状两次串行 LLM 调用（各 3-10s）。合并为一次调用输出 JSON：`{"rewritten": "...", "type": "global|local|impact"}`——prompt 合并、解析失败降级为原问题 + local（与现有降级语义一致）。合并后节点名变化同步 D2 的映射（rewrite_classify → 「正在理解问题…」）。

## D4 前端

- `useIndexProgress(projectId)`：EventSource 订阅（原生自动重连），onerror 超过 N 次回退 2s 轮询（保底不瞎）；详情页 StageBar / 列表页徽章共用
- 聊天：F7 loading 组件的文案源从计时器切到 stage 事件，无 stage 到达时保留计时兜底（兼容后端灰度）
- EventSource 天然带 cookie（同源），basePath 下 URL 用 API_BASE 拼接

## D5 验收口径

- 单测：broker 发布/订阅/满队列丢帧；SSE 端点快照+增量+终态关流（httpx ASGI 流式读）；stage 事件映射；合并调用解析与降级
- 手测：录入项目页面进度条平滑走完不发轮询请求（Network 面板核验）；聊天三阶段文案依次出现；断网重连恢复；服务器上线复测
