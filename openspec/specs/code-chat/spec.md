# code-chat Specification

## Purpose
代码聊天问答能力：在已索引就绪的项目下管理会话，基于 Neo4j 向量检索与 LangGraph 工作流生成流式回答并附带代码引用。

## Requirements

### Requirement: 会话管理
系统 SHALL 支持在指定项目下创建聊天会话、列出会话、查看会话历史消息；会话与消息持久化于 Postgres（chat_sessions / chat_messages）。

#### Scenario: 新建会话并保留历史
- **WHEN** 用户在项目下新建会话并完成一轮问答后刷新页面
- **THEN** 会话出现在列表中，历史消息完整可见

### Requirement: 项目就绪校验
聊天接口 MUST 校验目标项目状态为 ready；未就绪（pending/indexing/failed）时 SHALL 返回明确错误提示，不进行检索与生成。

#### Scenario: 对索引中的项目提问
- **WHEN** 项目状态为 indexing 时发起提问
- **THEN** 返回"项目索引未完成"类明确提示，不产生模型调用

### Requirement: 向量检索
问答流程的 retrieve 节点 SHALL 以问题向量在 Neo4j Chunk 向量索引上执行 top-k 检索（k 可配置，默认 8），且 MUST 按 project_id 过滤，仅返回目标项目的块。

#### Scenario: 跨项目隔离
- **WHEN** 两个项目都含同名函数 `create_order`，用户在项目 A 中提问
- **THEN** 检索结果仅包含项目 A 的代码块

### Requirement: 流式回答与引用
generate 节点 SHALL 将检索块组装为上下文，调用 OpenAI 兼容聊天模型（qwen3.7-plus / deepseek-v4-flash，环境变量切换）生成回答，通过 SSE 流式输出；回答完成后 MUST 持久化 assistant 消息及 citations_json（含 file_path、start_line、end_line、node_id），前端在回答下方展示可折叠的引用卡片（`路径:行号` + 代码预览）。

#### Scenario: 局部问题得到带引用回答
- **WHEN** 用户提问"parse_router 函数是干嘛的"且该函数已被索引
- **THEN** SSE 流式返回回答，结束后消息记录含至少一条指向该函数所在文件与行号区间的引用

#### Scenario: 模型调用失败
- **WHEN** 聊天模型 API 超时或报错
- **THEN** SSE 返回错误事件，前端提示重试，用户消息保留在会话中

### Requirement: LangGraph 工作流结构
问答 SHALL 实现为 LangGraph StateGraph（M1 为 retrieve → generate 两节点），检索逻辑封装在独立的检索服务层中供后续 MCP 复用；状态结构 SHALL 预留 rewrite/classify 节点的扩展位（M2 加节点不改状态模型）。

#### Scenario: 检索服务层独立可调用
- **WHEN** 不经聊天 API 直接调用检索服务（如后续 MCP 场景）
- **THEN** 传入 project_id + 查询文本即可获得与聊天一致的检索结果
