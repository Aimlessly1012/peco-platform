# RAG Coder — 代码 RAG 后台管理系统

拉取 GitLab/GitHub 仓库 → AST 分块 → 向量化 → Neo4j 知识图谱 → 选项目聊天问答（带代码引用）→ 项目理解报告 → MCP 供 Claude Code 等编码 agent 检索。

- 总设计：`docs/superpowers/specs/2026-08-11-rag-coder-design.md`（M1-M4 全貌）
- 当前进度：**M4 增量重索引 / 影响面多跳 / 可观测性**（OpenSpec change: `openspec/changes/m4-incremental-impact/`）

## 技术栈

FastAPI + LlamaIndex（Neo4jPropertyGraphStore）+ LangGraph + tree-sitter + Next.js；存储 Postgres（业务）+ Neo4j（代码图+向量）；模型走 OpenAI 兼容接口（默认本地 Ollama bge-m3 嵌入 + DeepSeek 对话，可换 DashScope）。

## 快速开始

```bash
cp .env.example .env
```

编辑 `.env`：填 `CHAT_API_KEY`、按需调整 `EMBEDDING_BASE_URL`，生成 `SECRET_KEY`。然后：

```bash
docker compose up -d --build
```

打开 http://localhost:3000。

- 后端 API: http://localhost:8001（宿主 8001 → 容器 8000；本机 8000 已被其他服务占用）
- MCP 端点: http://localhost:8001/mcp
- Neo4j Browser: http://localhost:7474（neo4j / ragcoder123）
- Postgres: localhost:5433（raguser / ragpass）

## 本地开发（不进容器）

```bash
docker compose up -d db neo4j
```

后端（`backend/` 目录）：

```bash
uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8001 --reload
```

前端（`frontend/` 目录）：

```bash
npm install && npm run dev
```

本地直跑后端时，在 `.env` 中取消注释 `DATABASE_URL` 与 `NEO4J_URI`（指向 localhost）。

## 索引模式（M4）

`POST /projects/{id}/index?mode=auto|full`，**默认 auto**。前端「重新索引」按钮走默认值。

- **auto**：项目有 `last_indexed_commit`、本地副本可用、`git diff` 可执行且图中有数据时走增量；任一不满足自动回退全量，并在任务 stats 记 `fallback_full_reason`。
- **full**：强制全量重建（增量出问题时的逃生门）。

增量语义：

| 对象 | 行为 |
|---|---|
| 新增/修改的文件 | 重解析、重摘要（hash 缓存未命中时）、重嵌入、重写节点 |
| 删除/改名的文件 | File 与其 DEFINES 的 Chunk 子图删除（改名 = 删旧 + 增新） |
| 未变更的文件 | 节点与向量原地保留，imports 与摘要从图读回，不读盘解析 AST |
| 结构边 | HAS_MODULE/CONTAINS/IMPORTS/CALLS_API 全量重连（归属与路由是全局计算） |
| 报告三件套 | 每次重算 |
| 无变更时 | 秒级 succeeded，stats 标 `no_changes`，图与报告不动 |

`last_indexed_commit` 仅在任务成功后更新；中途失败重跑仍以旧 commit 为基准。任务 `kind` 反映实际执行路径（`full` / `incremental`）。

正确性基准是**图等价**：增量产出的图必须与全量重建等价（同节点集、同边集、同内容 hash），由 `tests/test_incremental_integration.py` 钉住。

## 支持的路由框架

parse 阶段按框架探测器链解析路由并划分功能模块，前后端独立探测：

| 框架 | 识别方式 | 产出 |
|---|---|---|
| Next.js | `package.json` 含 `next` | `pages/`、`app/` 文件路由 → kind=page/api |
| umi | 依赖含 `umi`/`@umijs/max`，或存在 `.umirc.*` | 配置式（`.umirc.ts`、`config/routes.ts`、`config/config.ts` 的 routes 数组，`component: '@/pages/..'` 解析为入口文件）优先；否则约定式（`src/pages` 文件路由，支持 `[id]`/`$id` 动态段，排除 `_layout` 等下划线文件与 `components` 目录） |
| React Router v6 | 源码含 `createBrowserRouter(` 或 `<Route` | 路由首段分组 → kind=page |
| FastAPI | 路由装饰器 + `include_router` prefix 拼接 | kind=api，并产出后端路由表供 CALLS_API 匹配 |

> Vue 项目不在支持范围。未识别的框架统一走两级降级（页面目录感知分组 → 顶层目录分组，巨模块自动细分）。

全部探测失败时两级降级（stats 标 `router_fallback: true`）：优先按页面目录（`src/pages`、`src/views`、`app` 等）的二级子目录分组，否则按顶层目录分组（kind=dir）。任一模块归属文件数超过 200 时自动按子目录细分（递归，模块总数上限 60），避免出现"一个 src 模块装 1000 个文件"这种对检索无用的分组。

## MCP 接入

```bash
claude mcp add --transport http rag-coder http://localhost:8001/mcp
```

开启鉴权后（见下）需带上 header：

```bash
claude mcp add --transport http rag-coder http://localhost:8001/mcp --header "Authorization: Bearer <token>"
```

七个工具：`list_projects`、`get_project_overview`、`get_module_map`、`search_code`、`get_file_summary`、`impact_analysis`（多跳影响面，`max_depth` 默认 2、上限 3）、`get_project_understanding`。`GET /mcp-info` 返回当前实例的接入命令与工具清单（前端 `/mcp-guide` 页的数据源）。

## 关键配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `LLM_TIMEOUT_SECONDS` | 60 | 单次 LLM 调用超时，超时按退避重试，最终失败降级占位 |
| `EMBEDDING_TIMEOUT_SECONDS` | 30 | 单次嵌入调用超时（本地 Ollama 建议调大到 120） |
| `MCP_AUTH_TOKEN` | 空 | 非空时 `/mcp` 要求 `Authorization: Bearer <token>`，不匹配返回 401；为空保持本地免鉴权 |
| `MCP_ALLOWED_HOSTS` | 本机 + `backend:*` | MCP 的 DNS 重绑定防护白名单。MCP 无鉴权时这是唯一屏障，不要随意放开 |
| `SUMMARY_CONCURRENCY` | 4 | 摘要并发上限 |
| `EMBEDDING_BATCH_SIZE` | 10 | 嵌入批大小（也是 embed 阶段子进度的粒度） |

## 可观测性（M4）

六阶段进度：clone 0-10 → parse 10-25 → summarize 25-55 → embed 55-85 → graph 85-92 → report 92-100。summarize 按完成文件数、embed 按完成批次数在各自区间内连续推进（节流：每 5% 或 ≥2 秒），任务 stats 含 `summarize_done/total`、`embed_done/total`，千文件级仓库不再长时间停在同一个数字上。

增量任务的 stats 另含 `mode`、`changed_files`、`reparsed_files`、`reused_files`、`deleted_files`。

## 测试

```bash
cd backend && uv run pytest -m "not integration"
```

集成测试需要 Neo4j（`docker compose up -d neo4j`）：

```bash
cd backend && uv run pytest -m integration
```

## OpenSpec 工作流

```bash
openspec status --change m4-incremental-impact
```

继续实施 `/opsx:apply`；验证 `/opsx:verify`；归档 `/opsx:archive`。
