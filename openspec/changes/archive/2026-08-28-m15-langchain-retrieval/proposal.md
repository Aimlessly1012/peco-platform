## Why

检索链是全系统手写 Cypher 最集中的地方（向量查询、三路图扩展、RRF 合并全部手写），与已框架化的部分（LangGraph 编排、ChatOpenAI、LlamaIndex 图写入）形成断层。用户要求「LangChain 和 Neo4j 都用框架的东西，不要硬写」——把检索链重构为 LangChain 1.x 标准组件形状，补完「LangGraph 编排 + LangChain 检索 + LlamaIndex 图存储」的完整框架叙事。

## What Changes

- 向量检索层换 `langchain-neo4j` 的 `Neo4jVector.from_existing_index`，chunk/file/module 三路各一实例；图扩展（DEFINES 邻块 / CALLS_API / IMPORTS）的 Cypher 迁入 `retrieval_query` 定制插槽（Cypher 不消失，宿主从手写函数换成框架插槽）
- 嵌入调用对齐 LangChain `Embeddings` 接口（`OpenAIEmbeddings` 指向硅基流动），供 Neo4jVector 直接消费；批量/并发/截断护栏保留
- RRF 合并与重排走**当代 1.x 风格**：作为 LangGraph 节点内组件逻辑自持实现，不引入 `langchain-classic`（EnsembleRetriever 等已被官方归类为上一代）；rerank 的 httpx 调用包成组件形状（接口对齐，内部实现不变）
- **行为零变化**：引用 citations 的全部字段（路径/行号/via/score）、SSE 事件契约、top_k/超时参数逐一对齐，问答质量不回退
- graph_writer（已是 LlamaIndex + 性能所需的批量 Cypher）与向量索引 DDL 不在本次范围

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无——纯实现重构，code-chat 的行为需求不变，以既有 spec 场景与全量测试为回归契约）

## Impact

- 后端：`retrieval/service.py` 重写为框架组件形状、`embedder` 接口对齐、`reranker` 包装、`qa/workflow.py` 节点接线调整；新增依赖 `langchain-neo4j`
- 回归面：QA 核心路径——655 全量测试 + 引用字段级断言 + 线上实测对照
- 不受影响：索引管线、图写入、报告、鉴权、前端
