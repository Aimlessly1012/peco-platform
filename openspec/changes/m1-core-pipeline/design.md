# Design: M1 核心管道直线跑通

## Context

全新空仓库，完整系统设计已批准（`docs/superpowers/specs/2026-08-11-rag-coder-design.md`，下称"总设计"）。M1 是四个里程碑中的第一个，目标是验证三个新组件（tree-sitter / Neo4j / LlamaIndex）的集成风险并搭好骨架。技术栈沿用用户既有项目模式：FastAPI + uv + alembic + Next.js + Docker Compose。

## Goals / Non-Goals

**Goals:**

- Docker Compose 四容器一键起：backend / frontend / postgres / neo4j
- 项目 CRUD + 私有仓 token 加密存储 + 索引任务进度可见
- 索引直线：git clone → AST 分块 → 嵌入 → Neo4j 写入，单文件失败不中断，任务可重试
- 聊天直线：向量检索 top-k → LLM 生成 → SSE 流式 + `路径:行号` 引用
- 验收问题："XX 函数在哪/是干嘛的"能得到带引用的正确回答

**Non-Goals（后续里程碑）:**

- 路由解析、Module 节点、四层摘要、contextual embedding（M2）
- IMPORTS / CALLS_API 边、图扩展检索、问题分类（M2）
- 理解报告、MCP 工具（M3）
- 增量重索引、影响面分析（M4）——M1 重新索引 = 全量重建该项目子图

## Decisions

### D1: M1 就用 PropertyGraphIndex 手动建图，不走临时向量库

M1 图 schema 只建 `Project/File/Chunk` 节点 + `HAS_FILE`（M1 用 Project→File 直连，M2 插入 Module 层后改为 `HAS_MODULE`/`CONTAINS`）+ `DEFINES` 边，但**写入方式从第一天就用 `Neo4jPropertyGraphStore` + `EntityNode`/`Relation` 手动插入**。
理由：M2 要加 Module/IMPORTS/CALLS_API 时只是多插节点和边，无存储迁移；避免 M1 用 Neo4jVectorStore、M2 换 PropertyGraphIndex 的返工。
备选：M1 先 pgvector/Chroma——被总设计否决（双迁移成本）。

### D2: Chunk 向量索引在启动时幂等创建，维度取自环境变量

`EMBEDDING_DIM`（默认 1024，对应 text-embedding-v3）。后端启动时 `CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS`，若已存在但维度不符则报错拒启（防止静默检索错乱）。File/Module 摘要向量索引 M2 再建。

### D3: 索引任务 = 进程内 asyncio 任务 + Postgres 状态机，不引入队列

单用户一次一个索引任务：`POST /projects/{id}/index` 时若该项目已有 running 任务则 409。任务状态/阶段/进度写 `index_jobs` 表（stage: clone→parse→embed→graph，M1 无 summarize/report），前端 2s 轮询。进程重启后 running 任务由启动钩子标记为 stale-failed，可手动重触发。
备选：Celery/arq——单用户 YAGNI，总设计已否决。

### D4: AST 分块用 tree-sitter-language-pack，切块规则固定

- 语言：python / javascript / typescript / tsx（按扩展名路由，其余文件跳过并计数）
- 切块单位：顶层函数、类（类超过 token 上限按方法二次切）、导出组件；模块级零散语句合并为一个 module-level 块
- 块上限 ~1500 token（超长二次切，共享符号元数据）；跳过 >1MB 文件、二进制、node_modules/.git/dist 等忽略目录（.gitignore + 内置忽略表）
- 每块记录：symbol、symbol_type、start_line、end_line、code、content_hash

### D5: 嵌入批量 + content_hash 幂等缓存

DashScope 嵌入按批（batch=10，text-embedding-v3 单批上限）+ 并发上限 + 指数退避。写入前按 `(project_id, content_hash)` 查已有 Chunk，命中则复用向量（重试/重建时不重复计费）。M1 全量重建也因此天然省钱。

### D6: M1 聊天工作流用 LangGraph 两节点，结构为 M2 预留

`retrieve → generate` 两个节点的 StateGraph。retrieve 调检索服务（M1 = 纯向量 top-k，带 project_id 过滤）；generate 组装上下文 + 系统提示（要求引用出处），流式产出。M2 在同一张图前面加 rewrite/classify 节点即可。
聊天模型走 `ChatOpenAI(base_url=..., model=...)`，qwen3.7-plus / deepseek-v4-flash 由环境变量切换。

### D7: token 加密用 Fernet，密钥来自 SECRET_KEY 环境变量

`git_token_encrypted` 列存密文；clone 时解密拼入 https URL（`https://oauth2:<token>@gitlab...`），日志与 API 响应永不回显 token。

### D8: 前端 Next.js App Router + 最小依赖

页面：项目列表（含录入弹窗、进度条）、聊天页。SSE 用 fetch ReadableStream 解析。UI 组件用你惯用的 shadcn/ui 基础件，M1 不追求视觉打磨。

## Risks / Trade-offs

- [tree-sitter 语言包 ABI/版本坑] → 用 `tree-sitter-language-pack`（预编译全语言），Dockerfile 固定版本；集成测试在 CI 前置验证四种语言解析
- [Neo4j 向量索引维度写死后换嵌入模型] → D2 启动校验直接报错，提示需重建索引；换模型属于显式运维操作
- [DashScope 限流导致索引慢/失败] → 批量+退避+断点续跑（D5），进度条透明呈现
- [大仓库首次索引耗时长] → M1 接受；进度分阶段展示；忽略目录规则先砍掉最大头（node_modules 等）
- [M1 无摘要层，全局问题回答质量差] → 已知限制，验收只承诺局部问题；M2 解决
- [Project→File 直连在 M2 要改边] → 迁移脚本一条 Cypher 即可（插 Module 层重连），成本可控

## Migration Plan

全新项目无迁移。回滚 = 容器与 volume 删除重建。

## Open Questions

（无——总设计已批准，M1 范围内无待决问题）
