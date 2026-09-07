## ADDED Requirements

### Requirement: 重排服务商方言可切换
重排客户端 SHALL 支持多种服务商接口方言，由 `RERANK_PROVIDER` 选择，取值 `cohere`（默认）或 `dashscope`。默认值 SHALL 保持既有行为：未配置该项时请求与响应处理与引入本能力之前逐字节一致。

`dashscope` 方言下 `RERANK_BASE_URL` SHALL 被当作完整端点原样请求，SHALL NOT 追加 `/rerank` 或任何其他资源后缀；请求体 SHALL 为嵌套形状（`model` 在顶层，`query` 与 `documents` 在 `input`，`top_n` 在 `parameters`）；排名结果 SHALL 从 `output.results` 取出。

无论方言为何，失败哲学不变：任何异常、超时或无法解析的响应 SHALL 降级为 `None`，由调用方保持 RRF 原有顺序，SHALL NOT 阻塞问答。文档截断与空文档占位等共用预处理 SHALL 对所有方言一致生效。

#### Scenario: 未配置 provider 时沿用原有方言
- **WHEN** 环境未设置 `RERANK_PROVIDER`
- **THEN** 请求 URL 由 `RERANK_BASE_URL` 拼 `/rerank`，请求体为扁平形状，结果自顶层 `results` 解析

#### Scenario: dashscope 端点不被追加后缀
- **WHEN** `RERANK_PROVIDER=dashscope` 且 `RERANK_BASE_URL` 为含 WorkspaceId 的完整端点
- **THEN** 请求 URL 与配置值逐字节相同——追加后缀会得到 404，而 404 只会静默降级成「重排看起来没生效」，排查成本远高于失败本身

#### Scenario: 响应信封缺失时降级
- **WHEN** `dashscope` 响应中 `output` 缺失、为空或不是对象（如鉴权失败的错误体）
- **THEN** 返回 `None`，问答按 RRF 顺序正常完成
