# code-chat — M10 需求补录与引用口径修正（M17）

## ADDED Requirements

### Requirement: 上下文预算裁剪
检索在 RRF 融合（含可选 rerank 精排）与图扩展之后，SHALL 按 `CONTEXT_CHAR_BUDGET` 字符预算裁剪送入生成的资料条目：裁剪 SHALL 作用于 items 列表本身并保留前缀（保证答案 `[n]` 上标与 citations 下标一致），且 SHALL 至少保留 `context_min_items` 条；预算为 0 表示不裁剪。rerank 调用超时上限 SHALL 足以覆盖真实往返（默认 15s），避免精排长期静默降级。

#### Scenario: 预算裁剪不破坏引用编号
- **WHEN** 检索结果超出字符预算被裁剪
- **THEN** 保留的是原列表前缀，答案中的 `[n]` 仍精确对应第 n 条引用

#### Scenario: 资料不足时保底
- **WHEN** 预算极小
- **THEN** 仍保留至少 `context_min_items` 条资料，问答不因资料不足而失败

### Requirement: 生成与离线模型分流
问答的「答案生成」环节 SHALL 支持独立模型配置 `GENERATE_MODEL`（留空回落 `CHAT_MODEL`），与理解/分类环节解耦；索引摘要与报告件生成 SHALL 使用 `SUMMARY_MODEL`（留空回落 `CHAT_MODEL`），不受在线问答的模型选型影响。

#### Scenario: 生成与离线产出选型互不影响
- **WHEN** `CHAT_MODEL` 改为快速非推理模型、`SUMMARY_MODEL` 保持推理型模型
- **THEN** 问答走快模型，索引摘要与报告件仍走推理型模型

## MODIFIED Requirements

### Requirement: 流式回答与引用
generate 节点 SHALL 将检索块组装为上下文，调用 OpenAI 兼容聊天模型生成回答，通过 SSE 流式输出；回答完成后 MUST 持久化 assistant 消息及 citations_json。每条 citation SHALL 为七字段契约：`file_path`、`start_line`、`end_line`、`node_id`、`symbol`、`kind`、`via_edge`（不含 score；`kind` ∈ chunk/file_summary/module_summary，`via_edge` 为空表示直接命中）。前端在回答下方展示可折叠的引用卡片（`路径:行号` + 代码预览）。

#### Scenario: 局部问题得到带引用回答
- **WHEN** 用户提问"parse_router 函数是干嘛的"且该函数已被索引
- **THEN** SSE 流式返回回答，结束后消息记录含至少一条指向该函数所在文件与行号区间的引用

#### Scenario: 模型调用失败
- **WHEN** 聊天模型 API 超时或报错
- **THEN** SSE 返回错误事件，前端提示重试，用户消息保留在会话中

### Requirement: 检索实现基于框架组件
检索链 SHALL 基于 LangChain 1.x 组件实现（向量层 Neo4jVector + Embeddings 协议 + 组件化 rerank），SHALL NOT 以手写 driver 调用作为向量检索入口；图扩展等无框架 API 的定制查询 SHALL 收敛在框架提供的定制插槽或明确标注的外挂查询函数中。重构 SHALL 保持既有检索行为与引用契约不变。

#### Scenario: 引用契约不因重构变化
- **WHEN** 对同一项目提出与重构前相同的问题
- **THEN** citations 的七字段契约（file_path/start_line/end_line/node_id/symbol/kind/via_edge）与 SSE 事件契约与重构前一致

#### Scenario: 组件可替换
- **WHEN** 更换嵌入模型或 rerank 服务配置
- **THEN** 仅配置层变更即可生效，检索链代码不需要修改
