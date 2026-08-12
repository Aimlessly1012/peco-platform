# Tasks: M6 需求功能思维导图（B=后端会话 / F=前端会话 / V=PM 验收）

## 1. 后端 B 组

- [ ] B1 alembic 0004：understanding_reports 加 feature_map_markdown（nullable）；ReportOut/API 契约加字段
- [ ] B2 功能点提取器：单模块 prompt（业务名 + L3 + 路由清单 ≤15 → 2-6 条 ≤14 字中文动宾短语，禁技术词与清单外编造）+ 按模块 agg_hash 缓存（沿用 L3 缓存键体系与前缀排除规则）+ 失败降级路由段清单；shared 不入图、dir 模块程序化；单测覆盖提取降级与缓存（LLM mock）
- [ ] B3 markdown 拼装器：`# 项目名：L4 定位一句` → `## 功能域` → `- 功能点` 三层；kind 冲突名加后缀；fast 模式全程序化版本；单测断言层级结构与 mini_repo 功能域真实对应
- [ ] B4 report 阶段接线：deep 生成功能导图（与文档批生成并发）、fast 走程序化；stats 加 feature_points_new/cached；结构导图 mindmap_mermaid 照旧生成（供功能地图页签）

## 2. 前端 F 组

- [ ] F1 MarkmapView 组件：markmap-lib + markmap-view 动态 import 关 SSR，初始展开 depth=2，工具条（展开全部/收起/适应窗口/复制 markdown），渲染异常回退 markdown 文本；容器沿用终端风设计令牌，内部配色收敛 accent/ink
- [ ] F2 项目理解页签改版：主导图 = MarkmapView(feature_map_markdown)；为空回退 mermaid 旧导图 + 「重新索引获取功能导图」提示；结构导图与文件子导图移至功能地图页签顶部
- [ ] F3 npm run build 通过；lib/api.ts 类型补 feature_map_markdown

## 3. V 组（PM 验收）

- [ ] V1 全量测试绿 + 容器重建 + 容器代码核验（grep feature_map）
- [ ] V2 真实验收：ad.anynovel.app deep 重索引 → 功能导图为中文业务功能树（抽查 3 个功能域的功能点与实际页面对应）、markmap 折叠/展开/复制交互、复制的 markdown 粘贴 XMind 可用；fast 项目程序化功能导图可用；旧报告回退正常
- [ ] V3 提交与归档
