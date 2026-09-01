# code-chat — 分层检索与工作流升级（M2）

## MODIFIED Requirements

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

### Requirement: LangGraph 工作流结构
问答 SHALL 实现为 LangGraph StateGraph，节点为 rewrite → classify → retrieve → generate：rewrite 在存在会话历史时将追问改写为独立问题（无历史跳过）；classify 将问题分类为 global|local（分类失败默认 local）；retrieve 按类别执行分层检索。检索逻辑保持封装在独立的检索服务层中供后续 MCP 复用；状态模型沿用既有扩展位（rewritten_question/question_type），不做破坏性变更。

#### Scenario: 检索服务层独立可调用
- **WHEN** 不经聊天 API 直接调用检索服务（如后续 MCP 场景）
- **THEN** 传入 project_id + 查询文本即可获得与聊天一致的检索结果

#### Scenario: 追问被改写
- **WHEN** 用户先问"订单模块怎么实现的"，再追问"那它的取消逻辑呢"
- **THEN** rewrite 产出含"订单"上下文的独立问题，检索命中订单取消相关代码

#### Scenario: 分类失败安全回退
- **WHEN** classify 调用异常或输出无法解析
- **THEN** 按 local 策略检索，问答流程不中断
