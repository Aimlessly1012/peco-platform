# Proposal: M3 理解报告 + MCP 服务

## Why

M2 建成了理解层（模块地图、四层摘要、依赖图），但产物只能通过聊天问答被动消费。用户最初需求中还有两项未落地：①对目标代码自动生成"需求解释 + 思维导图 + 时序图"（总设计第 7 节）；②把代码检索能力通过 MCP 提供给 Claude Code 等编码 agent（总设计第 9 节）。M2 的图数据与摘要已把原料备齐，M3 把它们变成两种主动产物。

## What Changes

- 索引管道新增 **report 阶段**（六阶段：clone → parse → summarize → embed → graph → **report**）：自动生成项目理解报告三件套——需求逻辑文档（Markdown）、功能思维导图（Mermaid mindmap，程序化生成零幻觉）、核心流程时序图（Mermaid sequenceDiagram，每核心模块一张，语法校验 + 重试 + 文字降级）
- 新增 `understanding_reports` 表与报告查询 API、模块地图 API
- 新增 **MCP 服务**：FastMCP 以 streamable-http 挂载 `/mcp`，7 个工具（list_projects / get_project_overview / get_module_map / search_code / get_file_summary / impact_analysis / get_project_understanding），与聊天共用检索服务层
- 前端新增**项目详情页**（三页签：项目理解 / 功能地图 / 索引记录）与 **MCP 接入说明页**；进度条升为六阶段；mermaid 前端渲染 + 源码一键复制
- 不含（M4）：增量重索引、影响面多跳 Cypher 完整版（M3 的 impact_analysis 为一跳反查版）

## Capabilities

### New Capabilities

- `understanding-report`: 理解报告三件套的生成（report 阶段）、存储、查询 API、前端展示（项目理解/功能地图页签）与降级策略
- `mcp-service`: MCP 端点与 7 个工具的行为契约（返回精简 JSON + 行号定位、top_k 限制、项目隔离）、前端接入说明页

### Modified Capabilities

- `indexing-pipeline`: 「任务阶段推进与统计」加入 report 阶段（六阶段）
- `project-management`: 「索引任务进度查询」stage 枚举与进度条升为六阶段；项目详情页含索引记录页签

## Impact

- 代码：`backend/app/services/report/`（新增）、`backend/app/mcp_server/`（新增）、pipeline/tables/alembic 迁移、`frontend/app/projects/[id]/` 详情页、`frontend` mermaid 依赖
- 新增 Python 依赖：mcp（FastMCP）；前端依赖：mermaid
- 成本：每项目 report 阶段增加 LLM 调用 ≈ 1（文档）+ 核心模块数（时序图），flash 档几分钱级
- 无新容器；MCP 与后端同进程同端口
