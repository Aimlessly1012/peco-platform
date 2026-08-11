# understanding-report Specification

## Purpose
项目理解报告能力：索引管道 report 阶段为项目生成并持久化报告三件套（需求逻辑文档、功能思维导图、核心流程时序图），含生成降级与校验兜底；提供报告与模块地图查询 API，并在前端项目详情页可视化展示。

## Requirements

### Requirement: 报告三件套生成
索引管道 SHALL 新增 report 阶段（graph 之后），为项目生成并持久化理解报告：①需求逻辑文档（Markdown，LLM 基于 L4 总览 + 全部 L3 摘要 + 路由地图生成，按模块组织业务需求描述）；②功能思维导图（Mermaid mindmap，由 Project→Module→File 图数据程序化生成，不经 LLM）；③核心流程时序图（Mermaid sequenceDiagram，对 kind 为 api/page 且包含文件数 ≥2 的模块最多 6 个，LLM 基于模块摘要与 CALLS_API/IMPORTS 边生成）。报告 SHALL 按 project_id 覆盖写（一项目一份最新）。

#### Scenario: 索引完成自动产出报告
- **WHEN** 一个全栈项目索引任务成功完成
- **THEN** understanding_reports 中存在该项目记录，含非空 doc_markdown、mindmap_mermaid 与至少一张模块时序图

#### Scenario: 思维导图与图数据一致
- **WHEN** 查看生成的 mindmap 源码
- **THEN** 其模块与文件层级与 Neo4j 中 HAS_MODULE/CONTAINS 结构一致，不含图中不存在的名称

### Requirement: 报告生成降级与校验
时序图 mermaid 产出后 MUST 经后端启发式语法校验（类型声明行、参与者行、消息箭头行格式），失败自动重试 1 次，仍失败 SHALL 存 fallback_text（文字版调用链路）且不计为任务失败；需求逻辑文档生成失败 SHALL 降级为 L4+L3 原文拼接。report 阶段任何失败 MUST NOT 阻塞索引任务成功，仅将任务标记 partial。

#### Scenario: 单张时序图失败不影响其他
- **WHEN** 某模块时序图两次生成均校验失败
- **THEN** 该模块记录 fallback_text，其余模块时序图正常，索引任务仍为 succeeded

### Requirement: 报告与模块地图查询 API
系统 SHALL 提供 `GET /projects/{id}/report`（返回报告三件套；无报告时 404 并附提示语）与 `GET /projects/{id}/modules`（返回模块列表：name/kind/route_prefix/summary 及各模块文件清单与 L2 摘要，数据实时读 Neo4j）。

#### Scenario: 旧项目无报告
- **WHEN** 项目最后一次索引早于 report 功能上线，查询报告
- **THEN** 返回 404 与"请重新索引以生成报告"类提示

### Requirement: 前端项目理解展示
项目详情页 SHALL 含「项目理解」页签（渲染 doc_markdown、mindmap 与各模块时序图，每张图提供 mermaid 源码一键复制；渲染失败的图显示 fallback_text 或源码块）与「功能地图」页签（模块卡片展开文件清单与 L2 摘要）。mermaid SHALL 前端渲染（动态加载，渲染异常不得白屏）。

#### Scenario: 报告可视化与源码复制
- **WHEN** 用户打开已生成报告的项目详情「项目理解」页签
- **THEN** 文档、思维导图、时序图均渲染成功，点击复制按钮获得 mermaid 源码文本

#### Scenario: 渲染失败兜底
- **WHEN** 某张图 mermaid 前端渲染抛错
- **THEN** 该图位置显示 fallback_text 或源码块，页面其余部分正常
