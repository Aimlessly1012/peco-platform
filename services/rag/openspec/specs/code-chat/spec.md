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
问答流程的 retrieve 节点 SHALL 按问题类别执行分层混合检索，且 MUST 按 project_id 过滤：全局类问题以 module_summary_embedding 与 file_summary_embedding 两路向量检索为主，命中摘要节点后沿 CONTAINS/DEFINES 下钻代表代码块，并将 L4 项目总览注入上下文；局部类问题以 chunk_embedding 检索为主、file 摘要辅助。多路结果 SHALL 以 RRF 融合去重后截断（k 可配置，默认 8）。命中块 SHALL 经图扩展一跳补充：所属文件 L2 摘要、CALLS_API 对端块、IMPORTS 目标文件摘要，扩展结果标记 via_edge 供生成提示词区分直接命中与关联带出。

#### Scenario: 跨项目隔离
- **WHEN** 两个项目都含同名函数 `create_order`，用户在项目 A 中提问
- **THEN** 检索结果仅包含项目 A 的代码块

#### Scenario: 全局问题命中摘要层
- **WHEN** 用户提问"这个项目整体架构是什么"
- **THEN** 检索结果包含模块摘要节点且上下文含 L4 项目总览，回答能列出主要功能模块

#### Scenario: 前端块带出后端对端
- **WHEN** 检索命中一个含 fetch 调用的前端块，且该块存在 CALLS_API 边
- **THEN** 上下文中包含对端后端 handler 块，并标记为关联带出

### Requirement: 流式回答与引用
generate 节点 SHALL 将检索块组装为上下文，调用 OpenAI 兼容聊天模型（qwen3.7-plus / deepseek-v4-flash，环境变量切换）生成回答，通过 SSE 流式输出；回答完成后 MUST 持久化 assistant 消息及 citations_json（含 file_path、start_line、end_line、node_id），前端在回答下方展示可折叠的引用卡片（`路径:行号` + 代码预览）。

#### Scenario: 局部问题得到带引用回答
- **WHEN** 用户提问"parse_router 函数是干嘛的"且该函数已被索引
- **THEN** SSE 流式返回回答，结束后消息记录含至少一条指向该函数所在文件与行号区间的引用

#### Scenario: 模型调用失败
- **WHEN** 聊天模型 API 超时或报错
- **THEN** SSE 返回错误事件，前端提示重试，用户消息保留在会话中

### Requirement: LangGraph 工作流结构
问答 SHALL 实现为 LangGraph StateGraph，节点为 rewrite → classify → retrieve → generate：rewrite 在存在会话历史时将追问改写为独立问题（无历史跳过）；classify 将问题分类为 global|local|impact（分类失败默认 local）；retrieve 按类别执行对应检索策略（global/local 为分层检索，impact 为影响面检索）。检索逻辑保持封装在独立的检索服务层中供 MCP 复用；状态模型沿用既有扩展位，不做破坏性变更。

#### Scenario: 检索服务层独立可调用
- **WHEN** 不经聊天 API 直接调用检索服务（如后续 MCP 场景）
- **THEN** 传入 project_id + 查询文本即可获得与聊天一致的检索结果

#### Scenario: 追问被改写
- **WHEN** 用户先问"订单模块怎么实现的"，再追问"那它的取消逻辑呢"
- **THEN** rewrite 产出含"订单"上下文的独立问题，检索命中订单取消相关代码

#### Scenario: 分类失败安全回退
- **WHEN** classify 调用异常或输出无法解析
- **THEN** 按 local 策略检索，问答流程不中断

#### Scenario: 影响面问题被识别
- **WHEN** 用户提问"改 order_service.py 会影响哪些地方"
- **THEN** classify 输出 impact，retrieve 走影响面检索策略

### Requirement: 影响面检索
impact 类问题的检索 SHALL：先经向量检索定位目标文件（top 命中所在文件），再调用检索服务层的多跳影响查询（反向 IMPORTS 传播 max_depth≤3 + CALLS_API 前端调用方 + 波及模块聚合，结果上限 200），将影响树按深度分层格式化为资料并与常规检索结果合并送入生成；回答 SHALL 按深度分层描述影响面并给出出处。

#### Scenario: 多跳影响分层回答
- **WHEN** 被多层 import 的基础服务文件被问"修改它的影响"
- **THEN** 回答按 直接引用 / 间接（含深度）/ 波及前端与模块 分层列出，且带文件路径出处

#### Scenario: 目标定位失败降级
- **WHEN** 问题无法定位到明确目标文件
- **THEN** 退化为 local 策略正常回答，不报错

### Requirement: 检索实现基于框架组件
检索链 SHALL 基于 LangChain 1.x 组件实现（向量层 Neo4jVector + Embeddings 协议 + 组件化 rerank），SHALL NOT 以手写 driver 调用作为向量检索入口；图扩展等无框架 API 的定制查询 SHALL 收敛在框架提供的定制插槽或明确标注的外挂查询函数中。重构 SHALL 保持既有检索行为与引用契约不变。

#### Scenario: 引用契约不因重构变化
- **WHEN** 对同一项目提出与重构前相同的问题
- **THEN** citations 的字段结构（路径/行号/模块/via/score）与 SSE 事件契约与重构前一致

#### Scenario: 组件可替换
- **WHEN** 更换嵌入模型或 rerank 服务配置
- **THEN** 仅配置层变更即可生效，检索链代码不需要修改
