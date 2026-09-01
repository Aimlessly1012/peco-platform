# Design: M3 理解报告 + MCP 服务

## Context

M2 已交付理解层：Neo4j 中有 Module/File/Chunk 四层节点、IMPORTS/CALLS_API 边、L2/L3/L4 摘要，检索服务层（`services/retrieval/service.py`）为聊天与 MCP 共用而设计。M3 在此之上生成主动产物（报告）并开放 agent 接口（MCP）。本变更由两个并行工作流实施：后端（B 组任务）与前端（F 组任务），PM 负责集成验收（V 组）。

## Goals / Non-Goals

**Goals:**

- 索引完成即自动产出报告三件套，失败不阻塞索引成功（report 阶段的失败降级为占位文本，任务标 partial）
- Claude Code 通过 `claude mcp add --transport http rag-coder http://localhost:8001/mcp` 一行接入，7 工具可用
- 报告与 MCP 输出全部带可定位出处（文件路径/行号/模块名）
- mermaid 源码可复制、可版本管理、agent 可直读

**Non-Goals:**

- 增量重索引、影响面多跳完整版（M4）
- MCP 鉴权（个人本地工具，M4 若上远程再说）
- 报告的人工编辑与订正（只读产物，重索引重生成）

## Decisions

### D1: 报告生成的三种策略分开走（可靠性排序）

- **思维导图**：纯程序化生成——Cypher 读 `Project→Module→File` 树 + 路由前缀，模板拼 mermaid mindmap。零 LLM、零幻觉、必定成功
- **需求逻辑文档**：单次 LLM 调用，输入 = L4 总览 + 全部 L3 摘要 + 路由地图（结构化文本），输出分模块的业务需求描述（Markdown）。失败降级 = 直接拼接 L4 + L3 原文（仍是可读文档）
- **时序图**：每个"核心模块"（kind=api 或 page 且 CONTAINS 文件数 ≥ 2，上限 6 个）一张。输入 = 模块 L3 + 入口文件 L2 + 该模块相关 CALLS_API/IMPORTS 边清单，LLM 产 mermaid sequenceDiagram。**语法校验（后端启发式）失败重试 1 次，再失败存 fallback_text（文字版链路）**

### D2: mermaid 校验为后端启发式 + 前端兜底

后端无 JS 运行时，完整 mermaid parse 不做。启发式校验：首行类型声明合法（sequenceDiagram/mindmap）、participant/actor 行格式、箭头行 `A->>B: msg` 正则、无空 diagram。前端渲染以 mermaid.render try/catch 兜底：渲染失败显示 fallback_text 或源码块。双保险，两端都不会白屏。

### D3: understanding_reports 一项目一行，重索引覆盖写

`id, project_id(unique fk), doc_markdown, mindmap_mermaid, sequences_json([{module_key, module_name, mermaid, fallback_text}]), generated_at`。report 阶段 upsert；查询 API `GET /projects/{id}/report` 404 表示"索引早于 M3 或未完成"，前端提示重新索引。

### D4: MCP 用官方 python SDK（FastMCP）streamable-http 挂载同进程

`mcp_server/server.py` 定义 FastMCP 实例与 7 工具，`main.py` 以 `app.mount("/mcp", mcp.streamable_http_app())` 挂载（lifespan 合并注意：FastMCP 的 session manager 需要在 FastAPI lifespan 中一并启动）。工具实现全部调用既有服务层（retrieval / graph client / Postgres session），不重复检索逻辑。

### D5: 7 工具契约（输入输出要点）

| 工具 | 输入 | 输出（精简 JSON） |
|---|---|---|
| list_projects | - | [{id, name, status, modules_count, languages}] |
| get_project_overview | project(名称或 id) | {summary(L4), modules:[{name,kind,prefix,summary_head}]} |
| get_module_map | project | {mermaid_mindmap, modules:[{name,kind,files:[path]}]} |
| search_code | project, query, module?, top_k≤20 | [{file_path, lines, symbol, kind, snippet≤80行, via_edge?}] |
| get_file_summary | project, path | {summary(L2), symbols:[{name,type,lines}], imports, imported_by} |
| impact_analysis | project, file_or_symbol | {imported_by:[...], api_callers:[...], modules_affected:[...]}（一跳反查） |
| get_project_understanding | project | {doc_markdown, mindmap_mermaid, sequences:[...]} |

project 参数接受项目名或 uuid（名称唯一性不强制，重名取最新）。所有工具 project 不存在/未就绪时返回结构化错误信息（不抛裸异常）。

### D6: 前端详情页信息架构

`/projects/[id]` 三页签（客户端 tab，无子路由）：**项目理解**（文档 markdown 渲染 + 导图 + 各模块时序图，每图右上"复制源码"）、**功能地图**（模块卡片 → 展开文件列表 + L2 摘要，数据来自 `GET /projects/{id}/modules`）、**索引记录**（复用 jobs 接口，表格 + stats 展开）。列表页卡片新增「详情」入口。mermaid 用官方 npm 包动态 import（SSR 关闭），主题跟随页面。

### D7: 并行开发约定（B/F 两个 Opus 5 会话）

- 后端 agent 只改 `backend/`；前端 agent 只改 `frontend/`；**双方都不改 openspec/、不 commit、不起服务、不动对方目录**
- 接口契约以本文件 D3/D5 + specs 为准；前端在后端完成前用契约 mock 数据开发，验收阶段由 PM 联调
- tasks.md 勾选、测试运行、提交均由 PM（主会话）执行

## Risks / Trade-offs

- [时序图 LLM 产出质量不稳] → 输入给足结构化链路数据 + 校验重试 + 文字降级；每模块独立生成，单图失败不影响其他
- [FastMCP 与 FastAPI lifespan 集成的版本坑] → 后端任务明确要求先写一个最小挂载冒烟测试（TestClient 调 MCP initialize）再展开工具
- [mermaid 前端包体积大（~2MB）] → 动态 import 仅详情页加载；构建体积可接受（本地工具）
- [重名项目的 MCP project 参数歧义] → 取最新创建者并在返回中带 resolved_project_id，agent 可显式传 uuid

## Migration Plan

新表 alembic 迁移一条；旧项目无报告（API 404 → 前端引导重新索引）。无破坏性变更。

## Open Questions

（无）
