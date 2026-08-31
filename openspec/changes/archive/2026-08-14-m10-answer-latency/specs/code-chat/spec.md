# code-chat — 首答延迟优化（M10）

## MODIFIED Requirements

### Requirement: 分层混合检索
检索在 RRF 融合（含可选 rerank 精排）与图扩展之后，SHALL 按 `CONTEXT_CHAR_BUDGET`
字符预算裁剪送入生成的资料条目：裁剪 SHALL 作用于 items 列表本身并保留前缀
（保证答案 `[n]` 上标与 citations 下标一致），且 SHALL 至少保留 `context_min_items` 条；
预算为 0 表示不裁剪。rerank 调用超时上限 SHALL 足以覆盖真实往返（默认 15s），
避免精排长期静默降级。

#### Scenario: 预算裁剪不破坏引用编号
- **WHEN** 检索结果超出字符预算被裁剪
- **THEN** 保留的是原列表前缀，答案中的 `[n]` 仍精确对应右栏第 n 条引用

#### Scenario: 资料不足时保底
- **WHEN** 预算极小
- **THEN** 仍保留至少 context_min_items 条资料，问答不因资料不足而失败

### Requirement: 流式问答
问答的「答案生成」环节 SHALL 支持独立模型配置 `GENERATE_MODEL`（留空回落 `CHAT_MODEL`），
与理解/分类环节解耦；索引摘要与报告件生成 SHALL 使用 `SUMMARY_MODEL`（留空回落 `CHAT_MODEL`），
不受在线问答的模型选型影响。

#### Scenario: 生成与离线产出选型互不影响
- **WHEN** CHAT_MODEL 改为快速非推理模型、SUMMARY_MODEL 保持推理型模型
- **THEN** 问答走快模型，索引摘要与报告件仍走推理型模型
