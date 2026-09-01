# code-chat — 聊天阶段事件与前置调用合并（M9）

## MODIFIED Requirements

### Requirement: 流式问答
问答 SSE 流 SHALL 在 token 之前推送阶段事件 `event: stage`（data 含 stage 标识），对应工作流节点的开始时刻（理解问题 / 检索代码 / 生成回答）；前端等待期 SHALL 按 stage 事件展示真实阶段文案（无 stage 到达时保留计时兜底）。问题改写与类型分类 SHALL 合并为单次 LLM 调用（输出 JSON {rewritten, type}），解析失败降级为原问题 + local 类型；token/citations/done 事件行为不变。

#### Scenario: 等待期展示真实阶段
- **WHEN** 用户提问后等待首 token
- **THEN** 依次看到「正在理解问题…」「正在检索代码…」「正在生成回答…」阶段切换，而非静态文案

#### Scenario: 合并调用降级
- **WHEN** 合并的改写+分类调用超时或输出不可解析
- **THEN** 以原问题按 local 类型继续检索与回答，问答不失败
