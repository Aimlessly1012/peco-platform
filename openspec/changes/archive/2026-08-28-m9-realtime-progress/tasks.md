# Tasks: M9 实时进度与聊天阶段（B=后端 / F=前端 / V=PM 验收）

## 1. 后端 B 组

- [x] B1 进度 broker（services/ingest/progress_broker.py）：asyncio 队列 pub/sub、满队列丢旧帧、publish 非阻塞；pipeline on_progress 钩子接入发布；单测
- [x] B2 SSE 端点 GET /projects/{id}/progress（require_user）：首连快照（读最新 job）→ 增量 → 终态推送后关流；无运行任务直接关流；沿用 sse-starlette ping 与 sep="\n"；单测（ASGI 流式读：快照/增量/终态/无任务）
- [x] B3 聊天 stage 事件：chat.py 将 astream_events 的 on_chain_start（rewrite/classify/retrieve/generate 及合并后节点）映射为 event: stage；事件序 stage*→token*→citations→done；单测
- [x] B4 rewrite+classify 合并单次调用：prompt 输出 JSON {rewritten, type}，解析失败降级原问题+local；节点名同步 B3 映射；单测覆盖成功/降级；现有 549 测试保持绿

## 2. 前端 F 组

- [x] F1 useIndexProgress hook：EventSource 订阅（同源自动带 cookie、basePath 拼接）、自动重连、连续失败回退 2s 轮询；详情页 StageBar 与列表页状态徽章接入，下线常规轮询；build 两形态过
- [x] F2 聊天 loading 阶段化：F7 组件文案源切到 stage 事件（理解问题/检索代码/生成回答），无 stage 时计时兜底；与 F6 打字机衔接不变

## 3. V 组（PM 验收）

- [x] V1 全量单测绿 + 前后端 build + 容器核验
- [x] V2 本地实测：录入项目进度条平滑走完且 Network 无轮询；聊天三阶段文案；断线重连；首答耗时对比（合并调用应省 3-10s）
- [x] V3 服务器上线（查 indexing 后重建）+ 公网复测进度流与聊天阶段 + MCP/登录回归
- [x] V4 提交；归档由用户触发
