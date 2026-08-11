# Tasks: M3 理解报告 + MCP（B=后端会话 / F=前端会话 / V=PM 验收）

## 1. 后端 B 组（后端 Opus 5 会话执行，只改 backend/）

- [x] B1 understanding_reports 表（一项目一行 unique，字段见 design D3）+ alembic 迁移 0002；JobStage 加 REPORT；进度区间重划（graph 85-92，report 92-100）
- [x] B2 思维导图程序化生成器：Cypher 读 Project→Module→File 树 → mermaid mindmap 模板拼接（模块带 kind/route_prefix 标注），零 LLM；单测断言结构与转义
- [x] B3 需求逻辑文档生成：单次 LLM（输入 L4+全部 L3+路由地图结构化文本），失败降级为 L4+L3 拼接文档；mermaid 时序图生成：核心模块筛选（api/page 且文件≥2，上限 6）→ 输入模块 L3+入口 L2+相关边清单 → LLM 产 sequenceDiagram → 启发式校验（类型行/参与者/箭头正则）→ 失败重试 1 次 → fallback_text 降级；单测覆盖校验器与降级路径（LLM mock）
- [x] B4 report 阶段接入 pipeline（graph 后执行，upsert 报告，失败标 partial 不阻塞成功，stats 记 sequences_ok/sequences_fallback）
- [x] B5 API：GET /projects/{id}/report（404 附提示）与 GET /projects/{id}/modules（实时读 Neo4j：模块+文件+L2 摘要）
- [x] B6 MCP：mcp_server/server.py 定义 FastMCP 与 7 工具（契约见 design D5，复用 retrieval/graph/db 服务层，project 名称或 uuid 解析，结构化错误），main.py streamable-http 挂载 /mcp（lifespan 合并）；先写最小挂载冒烟测试（initialize + tools/list）再展开工具；工具级单测用假图数据或 mock

## 2. 前端 F 组（前端 Opus 5 会话执行，只改 frontend/）

- [x] F1 详情页骨架 /projects/[id]/page.tsx：三页签切换（项目理解/功能地图/索引记录），列表卡片加「详情」入口；进度条与类型升为六阶段（新增「生成报告」）
- [x] F2 项目理解页签：GET report → doc_markdown 渲染（react-markdown）+ mermaid 渲染组件（mermaid 动态 import、SSR 关闭、render try/catch 兜底显示 fallback_text 或源码）+ 每图「复制源码」按钮；404 时引导「重新索引以生成报告」
- [x] F3 功能地图页签（GET modules → 模块卡片按 kind 分组，展开文件清单+L2 摘要）与索引记录页签（GET jobs → 倒序表格，stats 可展开，失败显示 error_text）
- [x] F4 MCP 接入说明页 /mcp-guide：MCP URL、claude mcp add 命令一键复制、7 工具名称与用途表；顶栏加入口

## 3. V 组（PM 验收，主会话执行）

- [x] V1 后端测试全绿（单元+集成）+ 前端 build 通过 + 容器重建
- [x] V2 真实验收：重索引 tt-ad-agent 出报告三件套（详情页可视化验证）；Claude Code 实际添加 MCP 并调用 search_code/get_project_overview 成功
- [x] V3 提交与归档准备
