# Tasks: M2 理解层

## 1. 解析层扩展（路由 + 依赖边）

- [x] 1.1 IMPORTS 提取器：tree-sitter 解析 Python import/from 与 JS/TS import/require，相对路径解析为仓库内文件（含 index 文件与扩展名补全），三方包忽略；单测覆盖两种语言
- [x] 1.2 路由解析器框架探测器链：Next.js（pages/app 文件路由）、React Router v6、Vue Router、FastAPI（装饰器 + include_router prefix），前后端独立探测（按一级目录分区），统一输出 RouteModule；每框架配 fixture 单测（Next.js/FastAPI 用 mini_repo 实测；RR/Vue 为正则近似探测器）
- [x] 1.3 降级策略：全部探测失败按顶层目录分组（kind=dir），stats 标 router_fallback
- [x] 1.4 文件归属：入口直属 + 沿 IMPORTS 从入口 BFS 最近归属（等距多归属）+ shared 兜底；单测
- [x] 1.5 CALLS_API 匹配器：前端块 fetch/axios URL 字面量/简单模板串提取 → 规范化 → 与 FastAPI 路由表路径参数模式匹配；动态 URL 记 warning；用 mini_repo fixture 单测（orders.tsx ↔ routers/orders.py）

## 2. 摘要层

- [x] 2.1 摘要客户端：复用 OpenAI 兼容聊天客户端（flash 档模型可独立配置 SUMMARY_MODEL，默认同 CHAT_MODEL），并发上限 + 指数退避 + 失败降级符号清单
- [x] 2.2 L2 文件摘要：输入符号清单+头注释+import 列表；按 file content_hash 缓存（图删除前预读，同嵌入缓存模式）
- [x] 2.3 L3 模块摘要：输入模块内 L2+路由入口；缓存键为模块文件 hash 聚合；L4 项目总览：README+路由地图+全部 L3，每次重算
- [x] 2.4 管道接入 summarize 阶段（clone 0-10 → parse 10-25 → summarize 25-55 → embed 55-85 → graph 85-100），JobStage 加 SUMMARIZE，stats 记 modules/summaries_new/summaries_cached/api_edges

## 3. 图与嵌入升级

- [x] 3.1 上下文增强嵌入：L1 嵌入文本升级为带模块名/route_prefix/文件职责的上下文头；File 用 L2 文本、Module 用 L3 文本生成嵌入（缓存键修正为嵌入文本 hash，见 design 实施修正记录）
- [x] 3.2 graph_writer 扩展：Module 节点、HAS_MODULE/CONTAINS 边（停写 HAS_FILE）、IMPORTS/CALLS_API 边、File/Module 摘要与嵌入属性、Project.summary（模块唯一键 kind:name）
- [x] 3.3 向量索引：启动时幂等创建 file_summary_embedding 与 module_summary_embedding（与 chunk 索引同套维度校验逻辑）

## 4. 检索与工作流升级

- [x] 4.1 分层检索：module/file/chunk 三路向量查询（按类别配权）+ RRF 融合去重截断；全局类附 L4 注入
- [x] 4.2 图扩展一跳：命中块补充所属 File L2、CALLS_API 对端块、IMPORTS 目标 L2，标记 via_edge；generate 提示词区分直接命中/关联带出
- [x] 4.3 LangGraph 加 rewrite 节点（有历史时改写追问，无历史跳过）与 classify 节点（global|local，失败默认 local），retrieve 按类别选策略；generate 流打 tags=answer，SSE 层过滤避免内部节点输出混入答案

## 5. 前端与收尾

- [x] 5.1 进度条五阶段（新增「生成摘要」标签）
- [x] 5.2 集成测试扩展：mini_repo 断言 Module 节点与归属正确、CALLS_API 边连通、IMPORTS 边存在；全局问题检索命中摘要层（假向量）——单元 14 + 集成 2 全通过
- [x] 5.3 真实验收：重新索引 tt-ad-agent（6 模块、117 摘要、716 重嵌入、router_fallback=false）；全局问题"入口在哪/整体架构"得到准确回答（M1 曾答"未见入口"，M2 准确指出前后端入口、路由聚合、核心业务流，引用混合模块摘要/文件职责/代码三层）；追问验证 rewrite 节点上下文接续正确；chat 模块摘要失败降级如实标注推断——错误哲学符合设计
