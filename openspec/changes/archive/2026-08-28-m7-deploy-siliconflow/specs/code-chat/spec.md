# code-chat — Rerank 精排（M7）

## MODIFIED Requirements

### Requirement: 分层混合检索
检索 SHALL 按问题类型走分层混合策略（global 摘要层为主下钻 / local chunk 为主），多路向量召回经 RRF（k=60）融合；**配置了 rerank 时，RRF 融合出的候选池（top_k × 3）SHALL 经重排模型（`/v1/rerank`，Cohere 风格接口）精排后取 top_k**，再做图扩展一跳（CALLS_API / IMPORTS 邻居，via_edge 标记）。rerank 配置（RERANK_BASE_URL / RERANK_API_KEY / RERANK_MODEL）任一为空 SHALL 视为关闭，行为与 M6 完全一致；rerank 调用异常、超时（5s）或响应解析失败 SHALL 降级保持 RRF 顺序并记录 warning，不得阻塞或失败问答。影响面（impact）模式不走 rerank。

#### Scenario: rerank 提升精排质量
- **WHEN** rerank 三项配置齐全，用户提问命中候选池
- **THEN** 最终 top_k 顺序为重排模型的 relevance_score 降序（图扩展邻居除外），文档文本为 chunk 代码或摘要文本（每篇截前 1500 字符）

#### Scenario: rerank 未配置保持现状
- **WHEN** RERANK_API_KEY 为空
- **THEN** 检索行为与无 rerank 版本完全一致，不发起任何 /rerank 请求

#### Scenario: rerank 故障降级
- **WHEN** /v1/rerank 超时或返回不可解析内容
- **THEN** 按 RRF 融合顺序返回 top_k，问答正常完成，日志含降级 warning
