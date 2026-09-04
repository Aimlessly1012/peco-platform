# 换掉索引链路上最贵的两个模型

## Why

一次 onyx（5919 文件 / 40715 块）索引就把硅基流动余额烧空，且这笔钱有近一半是白花的：worker 被内存上限 OOM 杀掉后任务重投递，而第一遍的摘要没走到 graph 阶段、没落 Neo4j，缓存一条未留，重跑是全价。实测调用分布是 `chat/completions` 成功 5938 次对 `embeddings` 成功 669 次，摘要模型 `deepseek-ai/DeepSeek-V4-Flash` 的输出单价（¥4.5–9 / 百万 token）是账单里最重的一环；而嵌入若跑完，token 量约为摘要的六倍。

**为什么是现在**：换嵌入模型必须删掉三个 Neo4j 向量索引并全量重索引。当前图里只剩 ColaMD 一个项目、339 个节点，迁移代价约等于重跑一个 23 文件的小仓库。等索引了几个大仓库再换，同一件事就是把所有项目重烧一遍。这个窗口不会一直在。

顺带修一处失真：`indexing-pipeline` 的「嵌入向量化」需求把供应商写死成 DashScope text-embedding-v3，而线上早已是硅基流动 Qwen3-Embedding-8B。规格与现实不符会让下一个读它的人做出错误判断。

## What Changes

- **摘要模型**：`SUMMARY_MODEL` 从 `deepseek-ai/DeepSeek-V4-Flash` 换成低价候选（`Qwen/Qwen3.5-35B-A3B` ¥0.40 或 `inclusionAI/Ling-mini-2.0` ¥0.50）。它同时驱动三级摘要与理解报告生成，改一个字符串即全部生效，不影响任何历史数据。
- **嵌入模型**：`EMBEDDING_MODEL` 从 `Qwen/Qwen3-Embedding-8B`（4096 维）换成 `BAAI/bge-m3`（1024 维）。**BREAKING**：维度变更使已有向量全部失效，必须 DROP 三个向量索引并重索引全部项目。附带收益是向量存储降约 75%，缓解这台 3.6G 机器的内存压力。
- **重排模型**：`RERANK_MODEL` 从 `Qwen/Qwen3-Reranker-8B` 换成 `BAAI/bge-reranker-v2-m3`。量小，顺带做。
- **质量验收**：换模型前后各跑一次既有的真实模型评测档（`scripts/eval_retrieval.py` + `tests/eval/golden_set.json`），用指标对比而非主观判断决定是否保留新模型。
- **规格修正**：「嵌入向量化」需求去掉写死的供应商与模型名，改为配置驱动的表述，并补上「更换嵌入模型是一次受控迁移」的行为约定。
- **文档修正**：`.env.example` 声称「本项目当前不下发 dimensions 参数」，而 `embedder.py:47` 实际下发。这条注释误导性地关闭了 MRL 降维这个选项。

不做的事：不引入运行时可插拔的多供应商配置层（那是独立议题），不改重试与并发策略，不动 `CHAT_MODEL`（在线问答链路，本次不涉及）。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `indexing-pipeline`: 「嵌入向量化」需求从写死 DashScope text-embedding-v3 改为供应商与模型由配置决定；新增更换嵌入模型时的迁移语义——旧向量 SHALL 全部失效重建，不允许新旧向量空间共存。

## Impact

- **配置**：`services/rag/.env`（服务器与本地）、`services/rag/.env.example` 的默认值与注释。
- **数据**：Neo4j 三个向量索引需 DROP 重建；全部项目需重索引（当前仅 ColaMD 一个）。
- **规格**：`openspec/specs/indexing-pipeline/spec.md` 的「嵌入向量化」需求。
- **不涉及代码逻辑**：模型名与维度本就是配置项，`pipeline.py:431` 已有模型漂移检测、`graph/client.py:50` 已有维度校验，两者都会在迁移中自动生效。
- **前置依赖**：账户需先充值——余额为 0 时所有模型（含标称免费的 `BAAI/bge-m3`）一律返回 402，候选模型的可用性与实际维度因此尚未实测。
