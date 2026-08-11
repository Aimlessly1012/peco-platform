# indexing-pipeline — 理解层增强（M2）

## ADDED Requirements

### Requirement: 路由解析与模块归属
parse 阶段 SHALL 通过框架探测器链解析路由并划分功能模块：Next.js（pages/ 与 app/ 文件路由）、React Router v6（createBrowserRouter/Route 配置）、Vue Router（routes 配置数组）、FastAPI（路由装饰器 + include_router prefix 拼接）；前后端探测独立进行。文件归属规则：路由入口文件直接归属其模块；非入口文件沿 IMPORTS 边从模块入口 BFS 归属最近可达模块（等距可多归属）；不可达文件归 `shared` 模块。所有框架探测失败时 SHALL 降级为按顶层目录分组（kind=dir），任务 stats 标记 `router_fallback: true`，管道继续。

#### Scenario: 全栈仓库产出两类模块
- **WHEN** 索引一个 Next.js 前端 + FastAPI 后端的仓库
- **THEN** 产出 kind=page 的前端页面模块与 kind=api 的后端接口模块，各自的入口文件归属正确

#### Scenario: 未知框架降级
- **WHEN** 仓库无法被任何路由探测器识别
- **THEN** 按顶层目录划分模块，stats 含 router_fallback=true，索引正常完成

### Requirement: 依赖边提取
parse 阶段 SHALL 从 AST 提取仓库内依赖边：`(File)-[:IMPORTS]->(File)`（Python import/from 与 JS/TS import/require 的相对路径解析，三方包忽略）；`(Chunk)-[:CALLS_API]->(Chunk)`（前端块中 fetch/axios 的 URL 字面量与简单模板串，规范化后与后端路由表做路径参数模式匹配，指向后端 handler 块）。动态拼接无法解析的 URL SHALL 计入 stats warning 且不建边。

#### Scenario: 前后端调用边连通
- **WHEN** 前端 `orders.tsx` 含 `apiGet("/api/orders")` 且后端存在 `GET /api/orders` handler
- **THEN** 图中存在从该前端块到后端 handler 块的 CALLS_API 边

#### Scenario: 相对导入建边
- **WHEN** `routers/orders.py` 含 `from services.order_service import OrderService`
- **THEN** 图中存在 `routers/orders.py` 指向 `services/order_service.py` 的 IMPORTS 边

### Requirement: 四层摘要生成
索引管道 SHALL 新增 summarize 阶段生成三级摘要（与 L1 代码块合为四层理解）：L2 文件摘要（输入为符号清单+头部注释+import 列表）、L3 模块摘要（输入为模块内 L2 摘要+路由入口，含业务目标/关键流程/涉及文件）、L4 项目总览（输入为 README+路由地图+全部 L3）。L2 按文件 content_hash 缓存、L3 按模块文件 hash 集合的聚合 hash 缓存，命中不调用 LLM；L4 每次重算。单条摘要失败 SHALL 指数退避重试 3 次，仍失败降级为符号清单文本并将任务标记 partial，不中断管道。

#### Scenario: 摘要缓存生效
- **WHEN** 对内容未变化的项目再次全量索引
- **THEN** L2/L3 摘要不产生新的 LLM 调用（stats 中摘要缓存命中数与文件/模块数一致）

#### Scenario: 摘要失败降级
- **WHEN** 某文件摘要调用连续失败
- **THEN** 该文件以符号清单占位，任务完成且标记 partial

### Requirement: 上下文增强嵌入
embed 阶段的 L1 块嵌入文本 SHALL 采用上下文头格式（含项目名、所属模块名与 route_prefix、文件路径、符号、文件职责一句话），而非裸代码；File 节点 SHALL 以 L2 摘要文本嵌入、Module 节点以 L3 摘要文本嵌入。原始代码与嵌入文本分离存储。

#### Scenario: 块嵌入带模块上下文
- **WHEN** 查看任一 Chunk 的 context_text
- **THEN** 其中包含所属模块名与文件职责描述，而不仅是代码

## MODIFIED Requirements

### Requirement: Neo4j 图写入
graph 阶段 SHALL 通过 Neo4jPropertyGraphStore 手动插入方式写入：`(:Project {summary})`、`(:Module {name, route_prefix, kind, summary, embedding})`、`(:File {path, language, content_hash, summary, embedding})`、`(:Chunk {symbol, symbol_type, code, context_text, start_line, end_line, embedding})` 节点及 `(Project)-[:HAS_MODULE]->(Module)`、`(Module)-[:CONTAINS]->(File)`、`(File)-[:DEFINES]->(Chunk)`、`(File)-[:IMPORTS]->(File)`、`(Chunk)-[:CALLS_API]->(Chunk)` 边；所有节点 MUST 携带 project_id 属性实现项目隔离。后端启动时 SHALL 幂等创建三个向量索引（chunk_embedding、file_summary_embedding、module_summary_embedding，维度取 EMBEDDING_DIM），任一索引已存在但维度不符时 MUST 拒绝启动并给出重建指引。

#### Scenario: 写入后图结构可查
- **WHEN** 索引成功完成
- **THEN** Neo4j 中该 project_id 的 Module/File/Chunk 节点数与 stats 一致，每个 Chunk 经 DEFINES→CONTAINS→HAS_MODULE 链可回溯到所属模块与项目

#### Scenario: 向量索引维度冲突
- **WHEN** 启动时已存在维度 768 的任一向量索引而 EMBEDDING_DIM=1024
- **THEN** 后端启动失败并提示维度冲突与重建方法

#### Scenario: 摘要层可检索
- **WHEN** 以某模块业务相关的查询向量检索 module_summary_embedding 索引
- **THEN** 返回该模块节点及其 L3 摘要

### Requirement: 任务阶段推进与统计
索引任务 SHALL 按 clone → parse → summarize → embed → graph 顺序推进并实时更新 stage/progress/stats；每阶段完成即持久化，任务成功后项目状态置 ready。stats SHALL 额外记录模块数、摘要新调用数与缓存命中数、CALLS_API 边数与 warning 数。

#### Scenario: 阶段推进可观测
- **WHEN** 任务从 parse 进入 summarize
- **THEN** 任务记录的 stage 变为 summarize，progress 相应推进

#### Scenario: 理解层统计可见
- **WHEN** 索引成功完成
- **THEN** stats 含 modules、summaries_new、summaries_cached、api_edges 等计数
