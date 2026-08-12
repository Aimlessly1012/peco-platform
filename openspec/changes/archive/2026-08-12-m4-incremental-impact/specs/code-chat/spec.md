# code-chat — 影响面问答（M4）

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: 影响面检索
impact 类问题的检索 SHALL：先经向量检索定位目标文件（top 命中所在文件），再调用检索服务层的多跳影响查询（反向 IMPORTS 传播 max_depth≤3 + CALLS_API 前端调用方 + 波及模块聚合，结果上限 200），将影响树按深度分层格式化为资料并与常规检索结果合并送入生成；回答 SHALL 按深度分层描述影响面并给出出处。

#### Scenario: 多跳影响分层回答
- **WHEN** 被多层 import 的基础服务文件被问"修改它的影响"
- **THEN** 回答按 直接引用 / 间接（含深度）/ 波及前端与模块 分层列出，且带文件路径出处

#### Scenario: 目标定位失败降级
- **WHEN** 问题无法定位到明确目标文件
- **THEN** 退化为 local 策略正常回答，不报错
