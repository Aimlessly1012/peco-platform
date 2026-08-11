# RAG Coder — 代码 RAG 后台管理系统

拉取 GitLab/GitHub 仓库 → AST 分块 → 向量化 → Neo4j 知识图谱 → 选项目聊天问答（带代码引用）→ MCP 供 Claude Code 等编码 agent 检索。

- 总设计：`docs/superpowers/specs/2026-08-11-rag-coder-design.md`（M1-M4 全貌）
- 当前进度：**M1 核心管道**（OpenSpec change: `openspec/changes/m1-core-pipeline/`）

## 技术栈

FastAPI + LlamaIndex（Neo4jPropertyGraphStore）+ LangGraph + tree-sitter + Next.js；存储 Postgres（业务）+ Neo4j（代码图+向量）；模型 DashScope text-embedding-v3 + qwen/deepseek（OpenAI 兼容）。

## 快速开始

```bash
# 1. 配置
cp .env.example .env
# 编辑 .env：填 EMBEDDING_API_KEY / CHAT_API_KEY（DashScope），生成 SECRET_KEY

# 2. 启动（四容器：backend / frontend / db / neo4j）
docker compose up -d --build

# 3. 打开后台
open http://localhost:3000
```

- 后端 API: http://localhost:8001（宿主 8001 → 容器 8000；本机 8000 已被其他服务占用）
- Neo4j Browser: http://localhost:7474（neo4j / ragcoder123）
- Postgres: localhost:5433（raguser / ragpass）

## 本地开发（不进容器）

```bash
# 起依赖
docker compose up -d db neo4j

# 后端（backend/ 目录）
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8001 --reload

# 前端（frontend/ 目录）
cd frontend
npm install
npm run dev   # http://localhost:3000
```

本地直跑后端时，在 `.env` 中取消注释 `DATABASE_URL` 与 `NEO4J_URI`（指向 localhost）。

## 测试

```bash
cd backend
uv run pytest -m "not integration"     # 单元测试（分块器/加密），无外部依赖
docker compose up -d neo4j
uv run pytest -m integration           # 集成测试（图写入/检索冒烟），需 Neo4j
```

## M1 手动验收清单

1. `docker compose up -d --build` 全部容器 healthy
2. 后台录入一个真实仓库（私有仓填 token）→ 自动开始索引，卡片显示四阶段进度（拉取代码 → 解析分块 → 向量化 → 写入图谱）
3. 索引完成后状态变「就绪」，Neo4j Browser 中可见 `(:Project)-[:HAS_FILE]->(:File)-[:DEFINES]->(:Chunk)`
4. 进入聊天页提问「XX 函数在哪，是干嘛的」→ SSE 流式回答 + 引用卡片（`文件路径:行号`）
5. 触发「重新索引」→ 二次索引明显更快（content_hash 向量缓存生效，任务 stats 中 `embedded_cached` > 0）
6. 删除项目 → Neo4j 子图与本地副本一并清理

## 已知限制（后续里程碑解决）

- M1 只有向量检索，全局架构类问题回答质量有限 → M2 理解层（路由解析、四层摘要、图扩展检索）
- 未生成项目理解报告、无 MCP → M3
- 重新索引为全量重建（但向量按 content_hash 复用）→ M4 增量重索引

## OpenSpec 工作流

```bash
openspec status --change m1-core-pipeline   # 查看任务进度
# 继续实施: /opsx:apply；验证: /opsx:verify；归档: /opsx:archive
```
