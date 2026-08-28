## 1. 依赖与冒烟

- [ ] 1.1 加依赖 langchain-neo4j，与 langchain-core 1.5.x 兼容性冒烟（连本地 Neo4j 建 Neo4jVector.from_existing_index 跑一次向量查询）

## 2. 组件化重写

- [ ] 2.1 嵌入对齐 Embeddings 协议（OpenAIEmbeddings → 硅基流动），索引侧护栏不动
- [ ] 2.2 chunk/file/module 三路 Neo4jVector 实例 + retrieval_query 承载图扩展，metadata 逐字段对齐现有 citation
- [ ] 2.3 RRF 合并与 rerank 组件化（自持实现，不引 langchain-classic），qa/workflow 节点接线
- [ ] 2.4 旧实现保留一版对照（重构完成验收后删除）

## 3. 回归与验收

- [ ] 3.1 citations 字段级断言测试 + 既有全量回归全绿
- [ ] 3.2 部署后线上同题对照：重构前后各问一轮，引用命中与内容比对无回退
- [ ] 3.3 删除旧实现，收尾
