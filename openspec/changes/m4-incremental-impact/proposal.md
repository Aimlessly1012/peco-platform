# Proposal: M4 打磨 — 增量重索引 / 影响面多跳 / 大仓库可观测性

## Why

三个里程碑后系统功能完整，真实使用暴露了三类打磨点：①每次重新索引都全量重建，1151 文件级仓库即便缓存命中也要重跑全部解析与图重写，无变更时同样跑全程；②影响面分析只有一跳反查，"改这个文件会波及哪些页面"这类重构核心问题答不完整；③大仓库索引时 summarize/embed 阶段进度长时间静止（实测 ad.anynovel.app 卡显 25% 近十分钟），且 LLM 调用无显式超时，体验与健壮性有缺口。

## What Changes

- **增量重索引**：重新索引默认 auto 模式——项目存在 last_indexed_commit 且本地副本可用时走增量：git diff 出变更集；无变更秒级完成；有变更只重解析/重摘要/重嵌入变更文件，图做局部更新（变更 File 子图删重插 + 结构边全量重连），路由/归属/L3/L4/报告按既有 hash 缓存机制自然增量。支持 `mode=full` 强制全量。**BREAKING**（行为变化）：`POST /projects/{id}/index` 默认语义从全量变为 auto
- **影响面多跳**：impact_analysis 升级为有界多跳（反向 IMPORTS 传播 max_depth≤3 + CALLS_API 反查 + 波及模块/路由汇总，按深度分层输出）；聊天问题分类新增 impact 类，命中后走影响面专用检索策略
- **阶段内子进度**：summarize 按已完成文件数、embed 按已完成批次数实时推进 progress（25→55、55→85 区间内连续变化），stats 增加 summarize_done/summarize_total 与 embed_done/embed_total
- **LLM/嵌入调用显式超时**：单次调用 timeout 可配（默认 60s），超时进入既有退避/降级路径
- **MCP 可选鉴权**：MCP_AUTH_TOKEN 环境变量，设置后 /mcp 要求 Bearer 匹配；默认为空保持本地免鉴权

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `indexing-pipeline`: 移除「全量重建语义（M1）」，新增「重建与增量语义」「阶段内子进度」「模型调用超时」三条需求
- `project-management`: 「触发索引任务」加 mode 参数与增量语义描述
- `code-chat`: 「LangGraph 工作流结构」分类扩展 impact 类；新增「影响面检索」需求
- `mcp-service`: 「七个检索工具」的 impact_analysis 升级多跳；新增「可选鉴权」需求

## Impact

- 代码：`services/ingest/`（git diff、增量管道分支、进度回调）、`services/retrieval/`（impact 多跳 Cypher）、`services/qa/workflow.py`（impact 分类与策略）、`mcp_server/`（工具升级 + 鉴权中间件）、前端进度条消费子进度（无结构改动）
- 兼容：旧项目首次 auto 索引自动退化为全量（无 last_indexed_commit 或副本缺失）；无迁移
- 无新依赖、无新容器
