# Design: M2 理解层

## Context

M1 已跑通最细直线（AST 分块 → 向量 → Neo4j → 问答），真实验收确认了架构可行，也确认了纯块级向量检索回答不了全局问题。M2 在同一管道上加"理解"：路由地图、四层摘要、依赖边、分层检索。总设计第 5/6 节为依据；M1 的 `Neo4jPropertyGraphStore` 手动建图方式（D1）使本次扩展无存储迁移。

## Goals / Non-Goals

**Goals:**

- 索引产物从"代码块+向量"升级为"功能模块 → 文件 → 块"的带摘要图谱，含 IMPORTS/CALLS_API 边
- "登录流程怎么实现""项目架构什么样"类全局问题可回答（验收标准）
- 摘要成本可控：L2/L3 按内容 hash 缓存，重复索引近零 LLM 成本
- fixture 集成测试覆盖：模块划分正确、CALLS_API 连通前后端、全局问题命中摘要层

**Non-Goals:**

- 理解报告生成与 MCP 工具（M3）
- 增量重索引、影响面多跳 Cypher（M4）——M2 仍是全量重建
- Flask/Django 路由解析（视后续需要）；函数级精确 call graph（总设计明确不做）

## Decisions

### D1: 路由解析器按框架探测器链组织，输出统一的 ModuleMap

`router_parser.py` 定义 `detect(repo) -> list[RouteModule]`；探测器按序尝试：Next.js（存在 `pages/` 或 `app/` 且有 package.json 依赖 next）→ React Router（源码含 createBrowserRouter/`<Route`）→ Vue Router（routes 配置数组）→ FastAPI（装饰器 + include_router prefix 拼接）。前后端探测独立进行（全栈仓库同时产出 page 与 api 两类模块）。全部失败 → 降级：按顶层目录分组（kind=dir）并在任务 stats 标 `router_fallback: true`。
统一输出：`RouteModule {name, kind: page|api|dir|shared, route_prefix, entry_files}`。
备选：单一通用启发式——被否，框架路由语义差异太大，探测器链每个都简单可测。

### D2: 文件归属 = 入口直属 + import 可达性最近归属 + shared 兜底

路由入口文件直接归属其模块；非入口文件从各模块入口沿 IMPORTS 边 BFS，归属最近可达模块（距离相同归多个模块）；不可达文件归 `shared` 模块。IMPORTS 边在 parse 阶段由 tree-sitter 提取（Python import/from、JS/TS import/require 的相对路径解析为仓库内文件；三方包忽略）。
这意味着 parse 阶段先产 IMPORTS 边，summarize 阶段用它做归属——顺序依赖写进管道。

### D3: CALLS_API 匹配 = URL 字面量规范化 + 路径参数模式匹配

前端块内提取 `fetch(...)`/`axios.xxx(...)` 第一参数中的字符串字面量与简单模板串（`${var}` 段视为参数占位）；后端路由表来自 FastAPI 解析（method + path，path 参数 `{id}` 归一化）。匹配规则：method（可推断时）+ 路径段逐段比对，参数段互相通配。匹配不上或动态拼接 URL 记 stats warning，不建边。
边方向：`(前端 Chunk)-[:CALLS_API]->(后端 handler Chunk)`。

### D4: 四层摘要全部用结构化输入 + flash 模型，分层缓存

- **L2 文件摘要**：输入 = 文件符号清单 + 头部注释 + import 列表（不放全文，控 token）→ 一段中文职责描述。缓存键 `(file content_hash)`，图删除前与嵌入缓存一起预读。
- **L3 模块摘要**：输入 = 模块内全部 L2 摘要 + 路由入口签名 → 业务目标/关键流程/涉及文件。缓存键 = 模块内文件 hash 集合的聚合 hash。
- **L4 项目总览**：输入 = README（若有，截断）+ 路由地图 + 全部 L3 → 项目定位/架构/技术栈。每次重算（单次调用）。
- 失败处理：退避重试 3 次 → 降级为符号清单文本，任务标 partial（沿用 M1 错误哲学）。
- 并发上限沿用嵌入的 semaphore 模式，与嵌入共用「LLM 调用带宽」配置。

### D5: 摘要层向量索引独立建，检索三路并行

新增 `file_summary_embedding`（File.embedding，嵌入 L2 文本）与 `module_summary_embedding`（Module.embedding，嵌入 L3 文本）两个向量索引，启动时与 chunk 索引一起幂等创建/校验维度。L4 不建索引（每项目一份，全局问题直接注入上下文）。
检索时按问题类别选路：
- **全局**：module + file 两路向量检索 → 命中摘要 → 沿 CONTAINS/DEFINES 下钻取代表块 → 附 L4
- **局部**：chunk 一路为主 + file 摘要辅助
- 多路结果 RRF 融合（k=60 标准常数），截断 top-k 后进 generate。

### D6: 图扩展一跳作为检索后处理

命中 Chunk 后查询其：所属 File 的 L2 摘要、CALLS_API 对端块（前端命中带出后端 handler，反之亦然）、所属 File IMPORTS 目标的 L2 摘要（仅摘要，不带代码，控上下文）。扩展结果标记 `via_edge` 供 generate 提示词区分"直接命中/关联带出"。

### D7: LangGraph 图：rewrite → classify → retrieve → generate

- rewrite：有历史时把 follow-up 改写为独立问题（一次 flash 调用；无历史跳过）
- classify：LLM 单标签分类 global|local（带少样本；失败默认 local）
- retrieve 按 classify 结果选 D5 策略。State 沿用 M1 预留字段（rewritten_question/question_type），不改状态模型（兑现 M1 D6 的承诺）。

### D8: 管道阶段与进度重划

clone 0-10 → parse 10-25（含 IMPORTS/路由解析/归属）→ summarize 25-55 → embed 55-85 → graph 85-100。`JobStage` 加 `SUMMARIZE`；project-management 的任务查询接口无代码变化（stage 是自由字符串），仅 spec 与前端标签更新。

## Risks / Trade-offs

- [路由探测误判（如 monorepo 多框架混布）] → 探测器链按子目录独立探测（frontend/、backend/ 等一级目录各自跑）；误判兜底是 dir 降级，不阻塞
- [L3 缓存键对文件增删敏感，命中率低] → 可接受：L3 数量少（每项目 ~5-20 个模块），重算便宜；L2 才是大头且键稳定
- [CALLS_API 漏匹配（动态 URL）] → 按设计接受，记 warning；漏边只影响扩展召回，不影响主检索
- [classify 误分类] → 两类策略都会检索 chunk 层，差别是摘要层权重；误分类退化为 M1 水平而非出错
- [摘要调用拉长索引时长] → flash 档 + 并发 + 缓存；110 文件项目预计 summarize 阶段 1-3 分钟，进度条透明

## Migration Plan

无数据迁移：M1 项目重新索引即获得新图结构（全量重建删旧图）。graph_writer 停写 `HAS_FILE` 边，改写 `HAS_MODULE` + `CONTAINS`。新向量索引启动时自动创建。

## 实施修正记录

- **嵌入缓存键**：D4/D5 原定沿用 content_hash（代码 hash）——实施时修正为**嵌入文本 hash（embed_key）**：M2 嵌入文本含模块归属与文件职责，摘要变化必须使向量失效重算；M1 旧数据无 embed_key，首次 M2 重索引自然全量重嵌入，符合迁移语义
- **模块唯一键**：page:orders 与 api:orders 同名会在归属 BFS 与 Neo4j 节点名上冲突——模块键统一为 `"kind:name"`（Module 节点显示名存 module_name 属性）

## Open Questions

（无——范围内决策已闭合）
