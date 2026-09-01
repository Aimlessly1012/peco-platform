# understanding-report — 大项目报告质量（M5）

## MODIFIED Requirements

### Requirement: 报告三件套生成
索引管道 SHALL 在 report 阶段（graph 之后）为项目生成并持久化理解报告四件：①需求逻辑文档（Markdown，**map-reduce 分批生成**：模块按 kind 分组、每批 ≤10 个模块的 L3 摘要并发生成章节，最后以章节清单 + 路由地图生成系统概述）；②功能思维导图（Mermaid mindmap，**仅 Project→Module 两层**，节点标注 kind 与文件数，程序化生成）；③**模块数据流图**（Mermaid flowchart，模块间 CALLS_API 与跨模块 IMPORTS 聚合边，边标注数量、弱边省略、上限截断，程序化生成）；④核心流程时序图（对 kind 为 api/page 且文件数 ≥2 的模块最多 6 个，**输入瘦身**：模块 L3 + 入口 L2 ≤5 个 + 入口相关边各 ≤15 条，超限截断标注）。报告 SHALL 按 project_id 覆盖写。

#### Scenario: 索引完成自动产出报告
- **WHEN** 一个全栈项目索引任务成功完成（deep 模式）
- **THEN** understanding_reports 中存在该项目记录，含非空 doc_markdown、mindmap_mermaid、dataflow_mermaid 与至少一张模块时序图

#### Scenario: 大项目顶层导图可读
- **WHEN** 49 模块 / 1160 文件的项目生成报告
- **THEN** mindmap 节点数 ≤ 模块数 + 1（不含文件层），每个模块节点带文件数标注

#### Scenario: 数据流图与图数据一致
- **WHEN** 查看 dataflow_mermaid 源码
- **THEN** 其中每条边对应 Neo4j 中真实存在的模块间 CALLS_API 或 IMPORTS 聚合关系，不含图中不存在的模块

### Requirement: 报告生成降级与校验
时序图 mermaid 产出后 MUST 经后端启发式语法校验，失败重试 1 次，仍失败 SHALL 存 fallback_text 且不计任务失败。需求文档 SHALL 以**批为降级粒度**：单批章节生成失败仅该批以 L3 原文拼接并标注降级，其余章节正常；全部批失败才整篇降级为 L4+L3 拼接。程序化产物（顶层导图、数据流图）失败视为管道缺陷 MUST 修复，不设 LLM 类降级。report 阶段任何失败 MUST NOT 阻塞索引成功，仅标 partial。

#### Scenario: 单批失败不塌整篇
- **WHEN** 49 模块分 5 批生成文档，其中 1 批 LLM 调用失败
- **THEN** 文档其余 4 批章节与系统概述正常，仅失败批章节为拼接降级并标注，任务标 partial

#### Scenario: 单张时序图失败不影响其他
- **WHEN** 某模块时序图两次生成均校验失败
- **THEN** 该模块记录 fallback_text，其余模块时序图正常，索引任务仍为 succeeded

### Requirement: 报告与模块地图查询 API
系统 SHALL 提供 `GET /projects/{id}/report`（返回报告四件：doc_markdown、mindmap_mermaid、dataflow_mermaid、sequences，以及 depth 标记；无报告时 404 并附提示语）与 `GET /projects/{id}/modules`（返回模块列表：name/kind/route_prefix/summary 及各模块文件清单与 L2 摘要，数据实时读 Neo4j）。旧报告（无 dataflow_mermaid）字段可为空，客户端 SHALL 兼容。

#### Scenario: 旧项目无报告
- **WHEN** 项目最后一次索引早于 report 功能上线，查询报告
- **THEN** 返回 404 与"请重新索引以生成报告"类提示

### Requirement: 前端项目理解展示
项目详情页「项目理解」页签 SHALL 展示：需求文档（markdown 渲染 + 源码复制）、**模块级顶层导图**（点击模块节点或模块列表项 SHALL 展开该模块的文件子导图——由前端基于模块地图数据即时拼装渲染，无需后端存储）、**模块数据流图**、各模块时序图（渲染失败显示 fallback_text 或源码块，不得白屏）；每张图提供 mermaid 源码一键复制。fast 模式产物 SHALL 显示"快速模式"标识与「生成深度理解」引导。

#### Scenario: 模块子导图按需展开
- **WHEN** 用户点击顶层导图下方模块列表中的某模块
- **THEN** 渲染该模块的文件子导图（Module→Files），数据来自已加载的模块地图，无额外后端请求

#### Scenario: 渲染失败兜底
- **WHEN** 某张图 mermaid 前端渲染抛错
- **THEN** 该图位置显示 fallback_text 或源码块，页面其余部分正常
