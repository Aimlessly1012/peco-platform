# indexing-pipeline Specification

## Purpose
索引管道能力：按 clone → parse → summarize → embed → graph 阶段将 Git 仓库代码拉取、AST 分块（含路由解析、模块归属与依赖边提取）、四层摘要生成、上下文增强嵌入并写入 Neo4j 图谱，含文件过滤、全量重建语义与任务阶段推进统计。

## Requirements

### Requirement: 仓库拉取
索引任务的 clone 阶段 SHALL 将仓库 clone 至 `data/repos/<project_id>/`（已存在则 fetch+reset 到目标分支最新），私有仓使用解密后的 token 组装认证 URL。拉取失败（认证/网络/仓库不存在）时任务 MUST 置为 failed 并记录可读的 error_text。任务成功结束时 SHALL 记录 `last_indexed_commit`。

#### Scenario: 私有仓 token 无效
- **WHEN** clone 阶段认证失败
- **THEN** 任务 failed，error_text 包含"认证失败"类提示，不泄露 token 内容

#### Scenario: 重复索引复用本地副本
- **WHEN** 项目已有本地副本时再次索引
- **THEN** 执行 fetch+reset 而非重新 clone

### Requirement: AST 分块
parse 阶段 SHALL 使用 tree-sitter 解析 python/javascript/typescript/tsx 文件（按扩展名路由），切块单位为顶层函数、类（超长类按方法二次切）、导出组件，模块级零散语句合并为一个 module-level 块。每块 MUST 记录 symbol、symbol_type、start_line、end_line、code、content_hash。单块超过约 1500 token 时二次切分并共享符号元数据。

#### Scenario: 解析 Python 文件
- **WHEN** 文件包含 2 个顶层函数和 1 个类（3 个方法，类整体未超限）
- **THEN** 产出 2 个 function 块 + 1 个 class 块，各带正确的行号范围与符号名

#### Scenario: 单文件解析失败不中断
- **WHEN** 某文件语法错误导致解析失败
- **THEN** 跳过该文件、stats.skipped 计数 +1，管道继续处理后续文件

### Requirement: 文件过滤规则
parse 阶段 SHALL 跳过：.gitignore 匹配项、内置忽略目录（node_modules/.git/dist/build/.next/__pycache__/venv 等）、二进制文件、单文件 >1MB、非支持扩展名文件；跳过数计入 stats。

#### Scenario: 忽略 node_modules
- **WHEN** 仓库包含 node_modules 目录
- **THEN** 其中文件不产生任何块，也不计入解析文件数

### Requirement: 嵌入向量化
embed 阶段 SHALL 调用 DashScope text-embedding-v3（OpenAI 兼容配置，模型与维度由环境变量控制）对块的嵌入文本批量向量化（批大小 10），并发受限且对限流/超时按指数退避重试。相同 `(project_id, content_hash)` 的块 SHALL 复用已有向量，不重复调用 API。

#### Scenario: 断点续跑不重复计费
- **WHEN** 上次任务在 embed 阶段中断后重新触发索引
- **THEN** 已嵌入过（content_hash 未变）的块直接复用向量，仅新块调用嵌入 API

#### Scenario: 限流退避
- **WHEN** 嵌入 API 返回限流错误
- **THEN** 按指数退避重试，最终失败则任务 failed 并记录 error_text

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

### Requirement: 全量重建语义（M1）
M1 的重新索引 SHALL 为全量重建：先删除 Neo4j 中该 project_id 的全部节点与边，再执行完整管道写入（嵌入层面仍可按 content_hash 复用向量缓存）。

#### Scenario: 重新索引后无残留
- **WHEN** 对已 ready 项目触发重新索引且源码有文件被删除
- **THEN** 完成后 Neo4j 中不存在已删除文件对应的 File/Chunk 节点

### Requirement: 任务阶段推进与统计
索引任务 SHALL 按 clone → parse → summarize → embed → graph 顺序推进并实时更新 stage/progress/stats；每阶段完成即持久化，任务成功后项目状态置 ready。stats SHALL 额外记录模块数、摘要新调用数与缓存命中数、CALLS_API 边数与 warning 数。

#### Scenario: 阶段推进可观测
- **WHEN** 任务从 parse 进入 summarize
- **THEN** 任务记录的 stage 变为 summarize，progress 相应推进

#### Scenario: 理解层统计可见
- **WHEN** 索引成功完成
- **THEN** stats 含 modules、summaries_new、summaries_cached、api_edges 等计数

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
