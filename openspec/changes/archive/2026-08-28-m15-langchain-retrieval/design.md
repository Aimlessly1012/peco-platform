## Context

现状分层：LangGraph 1.2 编排四节点（understand→retrieve→rerank→generate）、langchain-openai 1.4 做 LLM、LlamaIndex 0.14 写图；唯独 retrieve 节点内部全手写——`_vector_query` 手写向量 Cypher，`expand_one_hop` 三路扩展，`_rrf_merge` 手写 RRF。锁定版本已是 LangChain 1.x 线，官方把 EnsembleRetriever/ContextualCompressionRetriever 归入 langchain-classic（上一代定位）。

## Goals / Non-Goals

**Goals:** 检索层组件化为 LangChain 1.x 标准形状；行为与引用质量零回退；组件可替换性（换向量库/rerank 只动配置层）。
**Non-Goals:** 不改检索算法本身（三路+RRF+rerank 的策略不动）；不动 graph_writer 与 DDL；不引 langchain-classic。

## Decisions

- **D1 当代 1.x 风格而非 classic 链**：Neo4jVector（langchain-neo4j 包）做向量层；RRF 与 rerank 作为 LangGraph retrieve/rerank 节点内的自持组件逻辑。理由：与既有 LangGraph 1.x 编排同代，避免「刚框架化就引入 legacy 组件」。
- **D2 图扩展 Cypher 迁入 retrieval_query**：Neo4jVector 的定制插槽完整支持附加 MATCH 与自定义返回列。三路扩展与 metadata（file_path/start_line/end_line/module/via）在插槽内逐字段对齐现有 citation 结构。定制代码图没有无 Cypher 的查询方式——框架化改变宿主与形状，不消灭 Cypher，这是刻意接受的边界。
- **D3 嵌入接口对齐**：OpenAIEmbeddings(base_url=硅基流动) 实现 LangChain Embeddings 协议供 Neo4jVector 消费；索引侧 embedder 的批量/退避/3000 字符截断护栏原样保留（两处共用底层配置，不强行合并实现）。
- **D4 rerank 包装不换内核**：硅基流动 rerank 非 OpenAI 标准接口且无官方 LangChain 集成，httpx 调用保留，外面包一层与节点签名对齐的组件类；15s 超时原序降级语义不变。
- **D5 回归契约**：以 citations 字段级断言 + 既有 SSE 契约测试 + 线上同题对照（改造前后各问一轮，引用命中与内容人工比对）作为「行为零变化」的验收标准。

## Risks / Trade-offs

- [retrieval_query 表达不下某路扩展] → 允许该路保留为独立 Cypher 查询函数（组件外挂），不为纯度牺牲正确性；design 允许混合形态
- [langchain-neo4j 与 langchain-core 1.5 兼容性] → 动手前先锁版本装包冒烟；不兼容则该包版本降级或上报改方案
- [检索结果顺序/分数尺度细微变化导致引用编号变动] → 字段级断言 + 同题对照把关；分数尺度变化在 rerank 层归一

## Migration Plan

依赖装包冒烟 → service.py 组件化重写（保留旧实现文件一版便于对照）→ 测试对齐 → 全量回归 → 部署 → 线上同题对照验收 → 删旧实现。

## Open Questions

（无）
