# Tasks: M1 核心管道直线跑通

## 1. 基础设施与骨架

- [x] 1.1 创建 monorepo 结构与 backend 工程（uv + pyproject，核心依赖：fastapi/sqlalchemy/alembic/llama-index 相关/langgraph/langchain-openai/tree-sitter-language-pack/GitPython/cryptography）
- [x] 1.2 编写 docker-compose.yml（backend/frontend/postgres16/neo4j5 四容器 + volumes）与 .env.example（数据库、Neo4j、嵌入与聊天模型 base_url/api_key/model、EMBEDDING_DIM、SECRET_KEY）
- [x] 1.3 FastAPI 应用骨架：配置加载（pydantic-settings）、健康检查、CORS、统一错误响应
- [x] 1.4 SQLAlchemy 模型与 alembic 初始迁移：projects / index_jobs / chat_sessions / chat_messages（字段按总设计第 8 节，M1 不建 understanding_reports）
- [x] 1.5 Neo4j 客户端封装：启动时幂等创建 Chunk 向量索引（维度=EMBEDDING_DIM），维度冲突拒绝启动并输出重建指引
- [x] 1.6 Fernet 加密工具（SECRET_KEY 派生），token 加解密 + 单测

## 2. 项目管理 API

- [x] 2.1 项目录入/列表/详情接口：token 加密入库、响应永不含 token、状态与最后索引信息返回
- [x] 2.2 删除项目接口：级联删除 Postgres 记录、Neo4j 该 project_id 全部节点边、data/repos 副本目录
- [x] 2.3 索引任务状态机：POST /projects/{id}/index（running 时 409）、任务查询接口（stage/progress/stats/error_text）、启动钩子将 running 任务标记 stale-failed

## 3. 索引管道

- [x] 3.1 git 拉取模块：clone / fetch+reset 到目标分支、token 认证 URL 组装、认证与网络错误转可读 error_text（不泄露 token）
- [x] 3.2 文件遍历与过滤：.gitignore 解析 + 内置忽略目录表 + 大小/二进制/扩展名过滤，产出待解析文件清单与 skipped 统计
- [x] 3.3 tree-sitter AST 分块器：python/javascript/typescript/tsx 四语言，顶层函数/类/组件切块 + module-level 合并块 + 超长二次切分，产出 symbol/symbol_type/行号/content_hash；单文件失败跳过；附各语言 fixture 单测
- [x] 3.4 嵌入客户端：DashScope text-embedding-v3（OpenAI 兼容），批大小 10、并发上限、指数退避
- [x] 3.5 向量复用缓存：按 (project_id, content_hash) 查询 Neo4j 已有向量，命中免调 API
- [x] 3.6 Neo4j 图写入：Neo4jPropertyGraphStore 手动插入 Project/File/Chunk 节点（全部带 project_id）与 HAS_FILE/DEFINES 边
- [x] 3.7 管道编排：asyncio 后台任务串联 clone→parse→embed→graph，阶段/进度/统计实时落库，全量重建先删旧子图，成功后项目置 ready、记录 last_indexed_commit

## 4. 聊天问答

- [x] 4.1 检索服务层：向量 top-k（默认 8）+ project_id 过滤，独立模块（后续 MCP 复用），返回块 + 文件路径 + 行号
- [x] 4.2 LangGraph 工作流：retrieve→generate 两节点 StateGraph，generate 组装上下文与引用要求提示词，流式产出 token 与末尾 citations；状态模型预留 rewrite/classify 扩展位
- [x] 4.3 聊天 API：会话创建/列表/历史、POST 提问（项目未 ready 明确报错）、SSE 流式响应、assistant 消息与 citations_json 持久化

## 5. 前端

- [x] 5.1 Next.js 骨架（App Router + Tailwind 基础件 + API client + SSE 解析工具）（实施调整：shadcn/ui 改为 Tailwind 手写同风格组件，M1 更薄）
- [x] 5.2 项目列表页：项目卡片（状态徽章/最后索引时间）、录入弹窗（url/token/分支）、索引进度条（2s 轮询 stage+progress）、重新索引与删除（二次确认）
- [x] 5.3 聊天页：会话侧栏、流式 markdown 渲染、引用卡片（路径:行号 + 折叠代码预览）、项目未就绪提示

## 6. 测试与验收

- [x] 6.1 构建微型 fixture 全栈仓库（9 文件：Next.js 页面 + fetch 调用 + FastAPI 端点，为 M2 的 CALLS_API 测试预埋素材）
- [x] 6.2 管道集成测试：对 fixture 跑完整索引（嵌入 mock 为固定假向量），断言 Neo4j File/Chunk 节点数、DEFINES 边数与 stats 一致（已对真实 Neo4j 跑通）
- [x] 6.3 检索冒烟测试：固定假向量下对 fixture 提出 3 个局部问题，断言检索命中预期文件的块（已跑通，含跨项目隔离断言）
- [ ] 6.4 手动验收：docker compose up → 录入一个真实私有仓库 → 索引完成 → 聊天问"XX 函数在哪/是干嘛的"得到带 路径:行号 引用的正确回答；README 记录启动与配置步骤（README 已写；API 冒烟已通过：health/创建/token 不回显/列表/删除级联；真实仓库验收需用户填入 DashScope key 后执行 README 验收清单）
