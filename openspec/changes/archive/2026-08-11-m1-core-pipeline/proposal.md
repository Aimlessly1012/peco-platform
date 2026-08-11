# Proposal: M1 核心管道直线跑通

## Why

RAG Coder 项目（代码 RAG 后台管理系统，完整设计见 `docs/superpowers/specs/2026-08-11-rag-coder-design.md`）需要第一个可验收的里程碑。M1 的目标是把风险最高的最细直线跑通：git 拉取 → AST 分块 → 嵌入 → Neo4j 写入 → 向量检索聊天，一次性验证 tree-sitter、Neo4j、LlamaIndex 三个新组件的集成可行性，为后续 M2（理解层）、M3（报告+MCP）、M4（打磨）奠定骨架。

## What Changes

- 从零搭建 monorepo：`backend/`（FastAPI + uv + alembic）+ `frontend/`（Next.js）+ Docker Compose 四容器（backend / frontend / postgres / neo4j）
- 新增项目管理能力：录入 Git 仓库（含私有仓 token，Fernet 加密）、项目列表/删除、索引任务状态与进度展示
- 新增索引管道（M1 精简版）：git clone/pull → tree-sitter AST 分块（python/js/ts/tsx）→ DashScope text-embedding-v3 嵌入 → Neo4j 写入 Chunk/File/Project 节点与 DEFINES 边
- 新增最简聊天问答：选择已就绪项目 → 向量检索 top-k 代码块 → OpenAI 兼容 LLM（qwen3.7-plus / deepseek-v4-flash）生成回答 → SSE 流式输出，带 `文件路径:行号` 引用
- 不含（后续里程碑）：路由解析、四层摘要、contextual embedding、图扩展检索、理解报告、MCP、增量重索引

## Capabilities

### New Capabilities

- `project-management`: 项目的录入（git url + 可选 token + 分支）、列表、删除；索引任务的触发、六阶段进度模型中 M1 用到的阶段（clone/parse/embed/graph）状态跟踪
- `indexing-pipeline`: M1 精简索引管道——仓库拉取、AST 分块、嵌入向量化、Neo4j 图写入；单文件失败跳过不中断、任务失败可重试
- `code-chat`: 面向单个已就绪项目的向量检索问答，SSE 流式输出与代码引用（路径:行号）

### Modified Capabilities

（无——全新项目，无既有 spec）

## Impact

- 新增全部代码：`backend/app/`（api / core / models / services/ingest / services/retrieval / services/qa）、`frontend/`、`docker-compose.yml`、alembic 初始迁移
- 新增外部依赖：Postgres 16、Neo4j 5.x（社区版，向量索引）、DashScope 嵌入 API、Qwen/DeepSeek OpenAI 兼容 API
- 新增 Python 依赖：fastapi、sqlalchemy、alembic、llama-index（core + graph-stores-neo4j + dashscope 嵌入）、langgraph、langchain-openai、tree-sitter 及语言包、GitPython、cryptography
- 环境变量：数据库连接、Neo4j 连接、嵌入/问答模型 base_url + api_key + model 名、SECRET_KEY（Fernet）
