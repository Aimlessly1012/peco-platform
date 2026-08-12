# indexing-pipeline Specification

## Purpose
索引管道能力：按 clone → parse → summarize → embed → graph → report 阶段将 Git 仓库代码拉取、AST 分块（含路由解析、模块归属与依赖边提取）、四层摘要生成、上下文增强嵌入、写入 Neo4j 图谱并生成理解报告，含文件过滤、重建与增量语义（auto/full）与任务阶段推进统计。

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

### Requirement: 任务阶段推进与统计
索引任务 SHALL 按 clone → parse → summarize → embed → graph → report 顺序推进并实时更新 stage/progress/stats；每阶段完成即持久化，任务成功后项目状态置 ready。stats SHALL 额外记录模块数、摘要新调用数与缓存命中数、CALLS_API 边数与 warning 数，以及报告生成情况（时序图成功/降级数）。

#### Scenario: 阶段推进可观测
- **WHEN** 任务从 parse 进入 summarize
- **THEN** 任务记录的 stage 变为 summarize，progress 相应推进

#### Scenario: 理解层统计可见
- **WHEN** 索引成功完成
- **THEN** stats 含 modules、summaries_new、summaries_cached、api_edges 等计数

#### Scenario: 报告阶段推进
- **WHEN** graph 阶段完成
- **THEN** 任务 stage 变为 report，报告生成完毕后任务 succeeded 且 stats 含 sequences_ok/sequences_fallback 计数

### Requirement: 路由解析与模块归属
parse 阶段 SHALL 通过框架探测器链解析路由并划分功能模块：Next.js（pages/ 与 app/ 文件路由）、umi（约定式 src/pages 文件路由与配置式 .umirc.ts / config/routes.ts / config/config.ts 路由数组，以 package.json 依赖 umi/@umijs/max 或 .umirc 存在为识别标志）、React Router v6（createBrowserRouter/Route 配置）、FastAPI（路由装饰器 + include_router prefix 拼接）；前后端探测独立进行。Vue Router 明确不在支持范围（Vue 项目不做，未知框架统一走两级降级）。文件归属规则：路由入口文件直接归属其模块；非入口文件沿 IMPORTS 边从模块入口 BFS 归属最近可达模块（等距可多归属）；不可达文件归 `shared` 模块。所有框架探测失败时 SHALL 两级降级：优先按页面目录感知分组（存在 src/pages、src/views、app 等页面目录时以其二级子目录为模块），否则按顶层目录分组（kind=dir）；任一模块 CONTAINS 文件数超过 200 时 SHALL 自动按其子目录进一步细分。降级发生时任务 stats 标记 `router_fallback: true`，管道继续。

#### Scenario: 全栈仓库产出两类模块
- **WHEN** 索引一个 Next.js 前端 + FastAPI 后端的仓库
- **THEN** 产出 kind=page 的前端页面模块与 kind=api 的后端接口模块，各自的入口文件归属正确

#### Scenario: umi 项目解析出页面模块
- **WHEN** 索引一个 umi 项目（package.json 含 @umijs/max，src/pages 下有多个页面目录）
- **THEN** 产出 kind=page 的页面模块（按路由首段分组），router_fallback 为 false

#### Scenario: 未知框架降级
- **WHEN** 仓库无法被任何路由探测器识别
- **THEN** 按两级降级策略分组，stats 含 router_fallback=true，索引正常完成

#### Scenario: 巨模块自动细分
- **WHEN** 任何分组方式产生文件数 >200 的模块
- **THEN** 该模块按子目录自动细分，最终无单模块超过 200 文件（不可细分的扁平目录除外）

### Requirement: 依赖边提取
parse 阶段 SHALL 从 AST 提取仓库内依赖边：`(File)-[:IMPORTS]->(File)`（Python import/from 与 JS/TS import/require 的相对路径解析，三方包忽略）；`(Chunk)-[:CALLS_API]->(Chunk)`（前端块中 fetch/axios 的 URL 字面量与简单模板串，规范化后与后端路由表做路径参数模式匹配，指向后端 handler 块）。动态拼接无法解析的 URL SHALL 计入 stats warning 且不建边。

#### Scenario: 前后端调用边连通
- **WHEN** 前端 `orders.tsx` 含 `apiGet("/api/orders")` 且后端存在 `GET /api/orders` handler
- **THEN** 图中存在从该前端块到后端 handler 块的 CALLS_API 边

#### Scenario: 相对导入建边
- **WHEN** `routers/orders.py` 含 `from services.order_service import OrderService`
- **THEN** 图中存在 `routers/orders.py` 指向 `services/order_service.py` 的 IMPORTS 边

### Requirement: 四层摘要生成
索引管道 SHALL 在 summarize 阶段生成三级摘要（与 L1 代码块合为四层理解）。L2 文件摘要 SHALL 先经**规则分级判定**，命中者以确定性规则摘要免 LLM 生成：测试文件（路径/文件名特征）、类型定义文件（.d.ts 或符号全为类型声明）、纯导出 barrel 文件、常量配置文件、总行数 <30 的小文件；规则摘要与 LLM 摘要同等进入缓存与嵌入。未命中者走 LLM，且输入按文件规模分级（<100 行仅符号签名；100-400 行减量头部与符号；更大者满额）。L3 模块摘要（输入为模块内 L2+路由入口）与 L4 项目总览机制不变。L2 按文件 content_hash 缓存、L3 按模块文件 hash 聚合缓存；单条摘要失败退避重试 3 次后降级符号清单占位并标 partial。stats SHALL 记录 summaries_rule（规则摘要数）与 summaries_new/summaries_cached。

#### Scenario: 规则文件免 LLM
- **WHEN** 索引含测试文件、.d.ts 类型文件与纯导出 index.ts 的项目
- **THEN** 这些文件获得规则摘要（内容含符号/来源清单），不产生 LLM 调用，stats.summaries_rule 相应计数

#### Scenario: 摘要缓存生效
- **WHEN** 对内容未变化的项目再次全量索引
- **THEN** L2/L3 摘要不产生新的 LLM 调用

#### Scenario: 摘要失败降级
- **WHEN** 某业务文件摘要调用连续失败
- **THEN** 该文件以符号清单占位，任务完成且标记 partial

### Requirement: 上下文增强嵌入
embed 阶段的 L1 块嵌入文本 SHALL 采用上下文头格式（含项目名、所属模块名与 route_prefix、文件路径、符号、文件职责一句话），而非裸代码；File 节点 SHALL 以 L2 摘要文本嵌入、Module 节点以 L3 摘要文本嵌入。原始代码与嵌入文本分离存储。

#### Scenario: 块嵌入带模块上下文
- **WHEN** 查看任一 Chunk 的 context_text
- **THEN** 其中包含所属模块名与文件职责描述，而不仅是代码

### Requirement: 重建与增量语义
重新索引 SHALL 支持 auto 与 full 两种模式（默认 auto）。auto 模式下，若项目存在 last_indexed_commit 且本地副本可用，SHALL 以 `git diff --name-status` 计算变更集执行增量：无变更时任务 SHALL 在秒级成功返回（stats 标 no_changes，不改动图与报告）；有变更时仅对新增/修改文件重解析、重摘要、重嵌入，删除/改名文件的 File 与 DEFINES 子图删除，未变更文件的节点与向量 MUST 保持不动；结构边（HAS_MODULE/CONTAINS/IMPORTS/CALLS_API）SHALL 全量重连；路由解析与归属全局重算（未变更文件的 imports 从图读回，不再读盘解析）。auto 判定不满足时 SHALL 回退全量并在 stats 记录 fallback_full_reason。last_indexed_commit MUST 仅在任务成功后更新。

#### Scenario: 无变更秒级返回
- **WHEN** 对已就绪项目触发 auto 索引且远端无新提交
- **THEN** 任务在秒级 succeeded，stats 含 no_changes=true，图与报告未发生写操作

#### Scenario: 增量与全量图等价
- **WHEN** 对同一变更集分别执行增量索引与强制全量索引
- **THEN** 两者产出的图等价（节点集、边集、内容 hash 一致），且增量路径中未变更文件保留原 embedding

#### Scenario: 删除文件无残留
- **WHEN** 变更集中包含删除的文件
- **THEN** 增量完成后图中不存在该文件的 File/Chunk 节点及其任何边

#### Scenario: 回退全量可解释
- **WHEN** 项目无 last_indexed_commit（或本地副本缺失）时触发 auto 索引
- **THEN** 执行全量流程，stats 含 fallback_full_reason

### Requirement: 阶段内子进度
summarize 阶段 SHALL 按已完成文件数、embed 阶段 SHALL 按已完成批次数在各自进度区间内连续推进 progress（节流：每 5% 或 ≥2 秒），stats SHALL 含 summarize_done/summarize_total 与 embed_done/embed_total。

#### Scenario: 大仓库进度连续可见
- **WHEN** 千文件级仓库处于 summarize 阶段
- **THEN** progress 在 25-55 区间随完成数持续增长，不长时间停驻单一数值

### Requirement: 模型调用超时
LLM 摘要与嵌入的单次调用 MUST 设置显式超时（环境变量可配，默认摘要 60s / 嵌入 30s），超时视为该次调用失败进入既有退避与降级路径。

#### Scenario: 单次调用挂起不阻塞管道
- **WHEN** 某次摘要调用超过超时上限无响应
- **THEN** 该调用被中止并按退避重试，最终失败则降级占位，管道继续

### Requirement: 索引深度模式
索引 SHALL 支持 depth=deep|fast（默认 deep）。fast 模式下 summarize 阶段全部使用规则/模板摘要（L2 规则或符号清单、L3 文件清单模板、L4 路由地图模板，零 LLM 调用），report 阶段仅生成程序化产物（顶层导图与数据流图），文档与时序图置空并在报告标记 depth=fast；路由地图、图结构、代码块嵌入与检索能力 MUST 与 deep 模式一致。项目记录最近索引深度；fast 项目可通过 depth=deep 的 auto 索引补跑深度理解（未变更内容走缓存，仅补 LLM 摘要与报告）。

#### Scenario: fast 模式零 LLM 录入
- **WHEN** 以 depth=fast 索引一个新项目
- **THEN** 任务成功且 summarize/report 阶段 LLM 调用数为 0，代码检索与功能地图正常可用

#### Scenario: fast 升级 deep 只补差价
- **WHEN** fast 索引过的项目在无代码变更时以 depth=deep 触发 auto 索引
- **THEN** 嵌入全部缓存复用，仅产生 LLM 摘要与报告生成调用，完成后报告为完整深度版
