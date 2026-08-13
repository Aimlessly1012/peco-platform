# Tasks: M6 需求功能思维导图（B=后端会话 / F=前端会话 / V=PM 验收）

## 1. 后端 B 组

- [x] B1 alembic 0004：understanding_reports 加 feature_map_markdown（nullable）；ReportOut/API 契约加字段
- [x] B2 功能点提取器：单模块 prompt（业务名 + L3 + 路由清单 ≤15 → 2-6 条 ≤14 字中文动宾短语，禁技术词与清单外编造）+ 按模块 agg_hash 缓存（沿用 L3 缓存键体系与前缀排除规则）+ 失败降级路由段清单；shared 不入图、dir 模块程序化；单测覆盖提取降级与缓存（LLM mock）
- [x] B3 markdown 拼装器：`# 项目名：L4 定位一句` → `## 功能域` → `- 功能点` 三层；kind 冲突名加后缀；fast 模式全程序化版本；单测断言层级结构与 mini_repo 功能域真实对应
- [x] B4 report 阶段接线：deep 生成功能导图（与文档批生成并发）、fast 走程序化；stats 加 feature_points_new/cached；结构导图 mindmap_mermaid 照旧生成（供功能地图页签）
- [x] B5 业务流程图（用户追加）：alembic 同迁移加 business_flows_json 列；单次 LLM 调用按 L4 核心业务流生成 2-4 张 flowchart TD（业务步骤节点 ≤8/张、文案 ≤12 字、禁文件名函数名），复用 mermaid 校验-重试-降级链路（fallback_text=业务流原文）；不缓存、fast 跳过；ReportOut 加 business_flows；单测覆盖校验降级（LLM mock）

- [x] B6 功能域业务归组（用户二次反馈：树状不平铺）：>8 功能域时 LLM 单次归组调用（输入功能域名+kind+L3 业务目标首句 → JSON {中文组名:[成员]}），程序化校验（成员真实、无重复、遗漏入「其他」、单组=失败），失败降级三层平铺；按功能域集合 hash 缓存；feature_map 变四层 markdown；单测覆盖校验降级
- [x] B7 页面结构导图：alembic 新列 page_map_markdown；按 page 模块路由 path 段程序化建树（产品→一级路由段→页面→逻辑要点，要点取功能点或 L2 首句压缩）；fast 同样生成（要点退化文件名）；ReportOut 加字段；单测

## 2. 前端 F 组

- [x] F1 MarkmapView 组件：markmap-lib + markmap-view 动态 import 关 SSR，初始展开 depth=2，工具条（展开全部/收起/适应窗口/复制 markdown），渲染异常回退 markdown 文本；容器沿用终端风设计令牌，内部配色收敛 accent/ink
- [x] F2 项目理解页签改版为纯需求视角：主导图 = MarkmapView(feature_map_markdown)（为空回退 mermaid 旧导图 + 提示）+ 业务流程图区块（business_flows 逐张 MermaidDiagram 渲染，空则隐藏）；**结构导图、文件子导图与模块数据流图全部移至功能地图页签**（用户定调：代码视角图归功能地图，代码细节靠聊天）
- [x] F3 npm run build 通过；lib/api.ts 类型补 feature_map_markdown 与 business_flows
- [x] F4 聊天页 UI 打磨（用户截图反馈追加）：①SOURCES 栏加宽至 ~300px + 条目重排（编号徽章 + 文件名主行 + 目录路径次行小字，长路径中段省略、hover 显全路径）②正文引用路径统一渲染组件（中段省略 + break-all 兜底 + hover 全路径）③[n] 上标可点击（sup 样式，点击滚动右栏对应条目并短暂高亮，右栏当前条目描边联动）④答案卡片与输入框间距收敛；build 通过

- [x] F5 页面结构导图卡片（复用 MarkmapView 渲染 page_map_markdown，置于功能导图之后）+ 四层功能导图初始展开层级调整（展开到业务组层，逐层点开）+ 旧报告无该字段隐藏卡片；build 通过
- [x] F6 功能地图页签打磨（用户截图反馈追加）：①模块结构导图从 Mermaid 静态图换 MarkmapView（modules 数据本地拼 `# 项目 → ## 模块类型 → ### 模块`，与功能导图同款 XMind 交互）②模块卡片网格 items-start（矮卡片不再被同行拉出大片空白）③模块摘要 overflow-wrap:anywhere（「核心文件」逗号长路径串不再顶破卡片）；build 通过

## 3. V 组（PM 验收）

- [x] V1 全量测试绿 + 容器重建 + 容器代码核验（grep feature_map）
- [x] V2 真实验收：ad.anynovel.app deep 重索引 → 功能导图为中文业务功能树（抽查 3 个功能域的功能点与实际页面对应）、markmap 折叠/展开/复制交互、复制的 markdown 粘贴 XMind 可用；fast 项目程序化功能导图可用；旧报告回退正常
- [x] V3 提交与归档
