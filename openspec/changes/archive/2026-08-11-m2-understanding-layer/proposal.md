# Proposal: M2 理解层

## Why

M1 验收暴露了纯向量检索的边界：真实项目问"入口在哪/主要流程是什么"，检索只命中局部相似的代码块，找不到承载全局语义的文件（回答如实承认"未见启动入口"）。总设计（`docs/superpowers/specs/2026-08-11-rag-coder-design.md` 第 5-6 节）的答案是理解层：索引时做整体解析——路由功能地图 + 四层摘要 + 上下文增强嵌入 + 依赖边，让"登录流程怎么实现""这个项目架构什么样"这类跨文件问题可回答。

## What Changes

- 索引管道新增 **summarize 阶段**（stage: clone → parse → **summarize** → embed → graph），生成 L2 文件摘要、L3 模块摘要、L4 项目总览（LLM flash 档，按 hash 缓存，失败降级符号清单）
- 新增**路由解析器**：Next.js（pages/app 文件路由）、React Router v6、Vue Router、FastAPI 装饰器路由 → 功能模块划分；无法识别框架时降级为按顶层目录分组
- 图 schema 扩展：新增 `(:Module)` 节点与 `HAS_MODULE`/`CONTAINS` 边（取代 M1 的 `HAS_FILE` 直连）、`(File)-[:IMPORTS]->(File)` 依赖边、`(Chunk)-[:CALLS_API]->(Chunk)` 前后端调用边；File/Module 摘要嵌入并新建两个向量索引
- **上下文增强嵌入**升级：L1 块嵌入文本带模块归属 + 文件职责头
- 检索升级为**分层混合检索**：问题分类（全局/局部）→ 全局优先命中 Module/File 摘要层再下钻，局部命中 Chunk 层；命中后沿 IMPORTS/CALLS_API/DEFINES **图扩展一跳**；多路结果 RRF 融合
- LangGraph 工作流激活 **rewrite**（多轮改写）与 **classify**（问题分类）节点（M1 已预留状态位）
- 前端索引进度条从 4 阶段变 5 阶段
- 不含（后续里程碑）：理解报告与 MCP（M3）、增量重索引与影响面多跳分析（M4）

## Capabilities

### New Capabilities

（无——理解层是对既有两个能力的深化，不新开 capability）

### Modified Capabilities

- `indexing-pipeline`: 新增路由解析与模块归属、四层摘要生成、依赖边提取（IMPORTS/CALLS_API）、上下文增强嵌入四条需求；修改「Neo4j 图写入」（schema 扩展 + 新向量索引）与「任务阶段推进与统计」（加入 summarize 阶段）
- `code-chat`: 修改「向量检索」为分层混合检索（摘要层 + 块层 + 图扩展 + RRF）；修改「LangGraph 工作流结构」（激活 rewrite/classify 节点）
- `project-management`: 修改「索引任务进度查询」（stage 枚举加入 summarize）

## Impact

- 代码：`services/ingest/`（新增 router_parser.py、summarizer.py、deps_extractor.py；修改 chunker 元数据、graph_writer、pipeline）、`services/retrieval/`（分层检索与融合）、`services/qa/workflow.py`（新节点）、`graph/client.py`（新向量索引）、前端进度条
- 成本：每次全量索引增加 LLM 摘要调用（~文件数 + 模块数 + 1 次；110 文件项目约 0.1-0.5 元 flash 档），L2/L3 按内容 hash 缓存使重复索引近零成本
- 兼容：M1 已索引项目需重新索引以获得新图结构（全量重建语义下自动完成，无迁移脚本）
- 无新增外部依赖与容器
