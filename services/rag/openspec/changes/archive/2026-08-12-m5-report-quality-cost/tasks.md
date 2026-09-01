# Tasks: M5 大项目报告质量 + 成本优化（B=后端会话 / F=前端会话 / V=PM 验收）

## 1. 后端 B 组 — 报告质量

- [x] B1 alembic 0003：understanding_reports 加 dataflow_mermaid（nullable）、projects 加 index_depth（默认 deep）
- [x] B2 顶层导图改两层（Project→Module，节点标注 kind 与文件数），移除文件层；单测断言大项目节点数 ≤ 模块数+1
- [x] B3 模块数据流图生成器：Cypher 聚合模块间 CALLS_API 与跨模块 IMPORTS → flowchart LR 模板（边标 xN、实/虚线区分、弱边 <2 省略、边上限 60 按权重截断标注）；用 mini_repo 断言边与图数据一致
- [x] B4 需求文档 map-reduce：按 kind 分组切批（≤10 模块/批）并发生成章节 + 章节清单生成系统概述；单批失败仅该批拼接降级；prompt 带统一格式约定；单测覆盖批降级粒度（LLM mock）
- [x] B5 时序图输入瘦身：模块 L3 + 入口 L2 ≤5 + 入口相关边各 ≤15，超限截断并在 prompt 注明；报告 API 返回结构加 dataflow_mermaid

## 2. 后端 B 组 — 成本优化

- [x] B6 规则分级摘要 rule_summary(file, chunks)：测试/类型定义/纯导出 barrel/常量配置/<30 行五类判定（保守条件）与摘要模板；stats 加 summaries_rule；每条规则单测
- [x] B7 L2 输入分级：<100 行仅符号签名、100-400 行减量、其余满额
- [x] B8 depth 模式：API ?depth= 贯通 → pipeline fast 分支（summarize 全规则/模板零 LLM、report 仅程序化两件+depth 标记）；Project.index_depth 记录；fast→deep auto 补跑路径验证（缓存复用）；集成测试断言 fast 零 LLM 调用（mock 计数）

## 3. 前端 F 组

- [x] F1 项目理解页签改版：顶层导图 + 模块列表点击展开子导图（前端由模块地图数据拼 mermaid mindmap 串，无后端请求）+ 数据流图卡片（dataflow 为空时隐藏）
- [x] F2 fast 模式标识与「生成深度理解」按钮（详情页，触发 depth=deep&mode=auto）；录入弹窗加深度选择（默认深度 + 成本提示一句）
- [x] F3 npm run build 通过；旧报告（无 dataflow）兼容展示

## 4. V 组（PM 验收）

- [x] V1 全量测试绿（单元 269 + 集成 35） + 容器重建（本次务必验证容器内代码为新版——上轮 build 缓存未生效问题）
- [x] V2 真实验收：ad.anynovel.app deep 重索引 → 顶层导图可读（≤50 节点）、数据流图正确、文档章节完整（≥4/5 批成功）、时序图成功率提升；新录入一个项目走 fast → 零 LLM 成本 + 检索可用 → 点「生成深度理解」补跑成功
- [x] V3 提交与归档
