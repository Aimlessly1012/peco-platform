# Design: M4 增量重索引 / 影响面多跳 / 可观测性

## Context

M1-M3 已归档，主 specs 为 5 能力基线。真实使用（1151 文件 / 5713 块的 ad.anynovel.app）确认三个打磨点：全量重建的浪费、影响面一跳的不足、长阶段进度静止。既有机制可复用：L2/L3 摘要 hash 缓存、embed_key 向量缓存、模块唯一键、检索服务层。

## Goals / Non-Goals

**Goals:**

- 无变更重索引 < 10 秒返回；小改动（<10 文件）重索引只对变更部分产生 LLM/嵌入成本与图写入
- "改 X 会影响什么"经聊天或 MCP 得到按深度分层、含波及模块的完整回答（深度 ≤3）
- 大仓库索引全程进度连续可见；单次模型调用有超时上限
- 全部行为有 fixture 级测试；增量正确性以"增量后图状态 = 全量重建图状态"为验收基准

**Non-Goals:**

- Webhook 自动触发（仍手动）；跨 commit 历史对比；报告 diff 视图
- 函数级精确 call graph（维持既有立场）
- MCP 完整 OAuth（只做静态 token）

## Decisions

### D1: 增量的边界——节点级增量、结构边全量重连、全局计算内存重算

diff（`git diff --name-status <old>..<new>`，R 视为 D+A）得到变更集后：

- **节点**：删除/改名旧路径与修改文件的 File+其 DEFINES Chunk 子图（DETACH DELETE）；新增/修改文件重解析重嵌入插入；**未变更文件的 File/Chunk 节点与向量完全不动**
- **结构边**（HAS_MODULE/CONTAINS/IMPORTS/CALLS_API）：先全删该项目此四类边再全量重连。理由：归属/路由/CALLS_API 是全局计算，且被删节点的入边会随 DETACH DELETE 消失，选择性修补的正确性成本远高于全量重连（边 upsert 千级 = 秒级）
- **全局计算**（路由解析/BFS 归属/CALLS_API 匹配）每次全量执行，但输入中未变更文件的 imports 与摘要从图中读回（新增 `load_file_metadata(project_id)` 读 File 节点 imports 属性——本次起 File 节点补存 imports 列表属性，老数据缺失时对该文件现场重提取），未变更文件不再读盘解析 AST
- **L2/L3/L4/报告**：机制不变（hash 缓存天然增量；L4 与报告每次重算，属可接受固定成本 ~7 次调用）
- 幂等基准：任务成功才更新 last_indexed_commit；中途失败重跑 auto 会以旧 commit 为基准重新 diff（缓存兜底重复成本）

### D2: 增量正确性的验收定义

集成测试以"**图等价**"断言：对 fixture 仓库做一次全量索引记录图快照（节点/边计数与关键属性），修改若干文件后分别走增量路径与全量路径，两者产出的图必须等价（同节点集、同边集、变更文件新 hash、未变更文件保留原 embedding 引用）。这是防增量腐化的唯一可靠标准。

### D3: mode 参数与判定

`POST /projects/{id}/index?mode=auto|full`（默认 auto）。auto 判定：project.last_indexed_commit 非空 且 `data/repos/<id>/.git` 存在 且 git diff 可执行 → 增量；任一不满足回退全量并在 stats 标 `fallback_full_reason`。无变更：不删不写图，任务 succeeded，stats `{no_changes: true}`，report 保留原样。

### D4: 影响面多跳 = 一条参数化 Cypher + 分层输出

```cypher
MATCH (start:File {project_id:$pid}) WHERE start.path IN $paths
CALL { WITH start MATCH p=(f:File)-[:IMPORTS*1..3]->(start)
       RETURN f, length(p) AS depth ORDER BY depth LIMIT 200 }
```
再叠加：受影响文件的 DEFINES 块中被 CALLS_API 指向的对端（前端调用方）、全部受影响文件的所属模块聚合。输出结构 `{direct:[...], transitive:[{file, depth, via_path}], frontend_callers:[...], modules_affected:[...]}`。深度上限 3、结果上限 200 防爆炸；起点支持文件路径或符号（符号先定位所在文件）。实现在检索服务层新增 `impact_of(project_id, file_or_symbol, max_depth)`，聊天与 MCP 共用。

### D5: classify 三分类与 impact 检索策略

CLASSIFY_PROMPT 扩为 global|local|impact（少样本补"改了 X 会影响哪些地方"类例句；失败仍回退 local）。impact 策略：先用问题定位目标（向量检索 top-3 取最优块所在文件）→ `impact_of` → 影响树格式化为资料（含深度与路径）→ 与常规 local 检索结果合并送 generate；提示词补充"影响面问题按深度分层回答"。

### D6: 子进度回调

pipeline 向 summarizer/embedder 传 `on_progress(done, total)` 回调，节流写库（每 5% 或 ≥2s 间隔）：summarize 区间 25-55 按文件完成数线性映射，embed 区间 55-85 按批次完成数映射。stats 增 `summarize_done/total`、`embed_done/total`。前端进度条零改动（吃 progress 数字），详情页索引记录可展示新 stats 键。

### D7: 超时与鉴权

- `LLM_TIMEOUT_SECONDS`（默认 60）与 `EMBEDDING_TIMEOUT_SECONDS`（默认 30）：AsyncOpenAI 客户端构造时传 timeout；超时异常进入既有退避重试 → 降级路径，不再依赖 SDK 默认 600s
- `MCP_AUTH_TOKEN`（默认空）：非空时以 ASGI 中间件拦截 /mcp 路径校验 `Authorization: Bearer`，401 返回结构化错误；接入说明页同步展示带 token 的配置命令（`claude mcp add --transport http rag-coder http://localhost:8001/mcp --header "Authorization: Bearer <token>"`）

## Risks / Trade-offs

- [增量与全量行为漂移] → D2 图等价测试钉死；任何增量 bug 的逃生门 = mode=full
- [结构边全量重连在超大仓库变慢] → 边 upsert 批量 500，5713 块级仓库实测秒级；若未来超十万边再优化为选择性修补
- [impact 多跳在循环依赖仓库结果膨胀] → 深度 ≤3 + LIMIT 200 + 路径去重；输出按模块聚合避免刷屏
- [File.imports 属性与 IMPORTS 边双源] → 属性仅作增量读回缓存，边仍是唯一真相源；写入时同一事务产出，不一致概率可忽略

## Migration Plan

无表结构变更。存量项目首次 auto 索引：File 节点无 imports 属性 → 该文件现场重提取（一次性成本），本次写入后补齐。回滚 = mode=full 永远可用。

## Open Questions

（无）
