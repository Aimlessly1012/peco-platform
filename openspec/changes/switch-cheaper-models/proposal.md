# 换掉索引链路上最贵的两个模型

## Why

一次 onyx（5919 文件 / 40715 块）索引就把硅基流动余额烧空，且这笔钱有近一半是白花的：worker 被内存上限 OOM 杀掉后任务重投递，而第一遍的摘要没走到 graph 阶段、没落 Neo4j，缓存一条未留，重跑是全价。实测调用分布是 `chat/completions` 成功 5938 次对 `embeddings` 成功 669 次，摘要模型 `deepseek-ai/DeepSeek-V4-Flash` 的输出单价（¥4.5–9 / 百万 token）是账单里最重的一环；而嵌入若跑完，token 量约为摘要的六倍。

**为什么是现在**：换嵌入模型必须删掉三个 Neo4j 向量索引并全量重索引。当前图里只剩 ColaMD 一个项目、339 个节点，迁移代价约等于重跑一个 23 文件的小仓库。等索引了几个大仓库再换，同一件事就是把所有项目重烧一遍。这个窗口不会一直在。

顺带修一处失真：`indexing-pipeline` 的「嵌入向量化」需求把供应商写死成 DashScope text-embedding-v3，而线上早已是硅基流动 Qwen3-Embedding-8B。规格与现实不符会让下一个读它的人做出错误判断。

## What Changes

**供应商整体切到阿里百炼 DashScope（用户决定，2026-09-07）**，`baseUrl` 统一为
`https://dashscope.aliyuncs.com/compatible-mode/v1`，嵌入与对话共用同一把 key。四个槽位的定案：

- **摘要模型** `SUMMARY_MODEL`：`deepseek-ai/DeepSeek-V4-Flash`（¥1.5–3 / ¥4.5–9）→ `qwen3.8-flash`（¥1 / ¥3）。它同时驱动三级摘要与理解报告生成，改一个字符串即全部生效，不影响任何历史数据。
- **问答模型** `CHAT_MODEL`：`Qwen/Qwen3-Coder-30B-A3B-Instruct` → `qwen3.8-flash`。在线问答的回答生成走它；`GENERATE_MODEL` 留空复用。
- **嵌入模型** `EMBEDDING_MODEL` + `EMBEDDING_DIM`：`Qwen/Qwen3-Embedding-8B`（4096 维）→ `qwen3.7-text-embedding-flash`（1024 维，¥0.125/M）。**BREAKING**：维度变更使已有向量全部失效，必须 DROP 三个向量索引并重索引全部项目。附带收益是向量存储降约 75%。
- **重排模型** `RERANK_MODEL`：`Qwen/Qwen3-Reranker-8B` → `qwen3.7-text-rerank`。**需要代码适配**：百炼这个模型走原生嵌套格式与带 WorkspaceId 的独立域名，现有客户端是 Cohere 风格，加一个 `RERANK_PROVIDER` 开关（默认 `cohere`，行为不变）。
- **质量验收**：换模型前后各跑一次既有的真实模型评测档（`scripts/eval_retrieval.py` + `tests/eval/golden_set.json`），用指标对比而非主观判断决定是否保留新模型。
- **规格修正**：「嵌入向量化」需求去掉写死的供应商与模型名，改为配置驱动的表述，并补上「更换嵌入模型是一次受控迁移」的行为约定。
- **文档修正**：`.env.example` 关于 `dimensions` 参数的错误说明已随 `5353a4a` 修正（自动部署验证时顺手做的）。

不做的事：不引入运行时可插拔的多供应商配置层（那是独立议题），不改重试与并发策略。

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
- **前置依赖**：用户的百炼 key 需先放进本地 `~/.peco-dashscope.key`（600 权限，脚本读文件不回显），探针用它实测四个模型的可用性与嵌入实际返回维度；重排还需要百炼控制台的 WorkspaceId。
- **代码改动**：`services/rag/app/services/retrieval/reranker.py` 与 `app/core/config.py` 加 provider 开关（已派给执行会话）。
