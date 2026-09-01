# Design: M5 大项目报告质量 + 索引成本优化

## Context

四里程碑已归档，主 specs 为 5 能力 35 需求基线。真实大项目（49 模块/1160 文件/5843 块）实测暴露报告规模化失效与摘要成本问题。既有可复用机制：L2/L3 hash 缓存、报告 upsert、模块地图 API（前端已有全量模块+文件数据）、mermaid 启发式校验与降级、六阶段管道。

## Goals / Non-Goals

**Goals:**

- 49 模块级项目的报告四件全部可读可用：顶层导图 ≤60 节点、文档章节完整率 ≥90%、时序图 mermaid 成功率明显提升、新增模块数据流图
- 中型项目首次录入摘要 LLM 调用量降至 ~1/3（规则分级）；fast 模式录入 LLM 调用 ≈ 0
- 全部改动向后兼容：旧报告可展示、深度模式默认 deep 行为不变

**Non-Goals:**

- 报告人工编辑；函数级流程图（模块级数据流图已覆盖"流程图"诉求）
- 摘要质量评测体系（人工抽查即可）

## Decisions

### D1: 导图分层 = 后端顶图 + 前端即时子图

- 后端 mindmap 只画 `Project → Module`（节点文案 `模块名 (kind, N 文件)`），49 模块 ≈ 50 节点，任何项目都可读
- 模块子导图（Module → Files）**前端拼装**：`GET /projects/{id}/modules` 已返回全部模块+文件数据，点击模块时前端模板拼 mermaid mindmap 串渲染——零后端存储、零 LLM、点开即得
- 理由：子图数据前端已有，后端预生成 49 张子图纯属浪费存储与生成时间

### D2: 模块数据流图 = 图聚合查询 + flowchart 模板

Cypher 聚合：模块对之间的 CALLS_API 边数与跨模块 IMPORTS 边数 → `flowchart LR` 模板（边标注 `xN`，CALLS_API 实线 / IMPORTS 虚线，边数 <2 的弱关联省略防爆炸，节点按 kind 分色 class）。报告表新增 `dataflow_mermaid` 列（alembic 0003）。程序化零 LLM，与思维导图同属"必然成功"档。

### D3: 文档分批 = map-reduce 两级生成

- map：模块按 kind 分组切批（每批 ≤10 模块的 L3），并发生成"功能模块需求"章节（沿用 summary 客户端与退避）
- reduce：以各章节标题清单 + 路由地图生成"系统概述"（单次小调用）
- 失败粒度：单批失败仅该批章节用 L3 原文拼接并标注，其余正常；全部失败才整篇降级（保留现兜底）
- 顺带修因：现挂载单 prompt 超限问题消失（每批输入 ≤ ~8k token）

### D4: 时序图输入瘦身

输入从"模块 L3 + 全部入口 L2 + 模块相关全部边"收紧为：模块 L3 + 入口文件 L2（≤5 个）+ 入口文件出发的 CALLS_API/IMPORTS 边（各 ≤15 条）；超限截断并在 prompt 中注明"仅展示主链路"。生成侧不变（校验/重试/降级保留）。

### D5: 规则分级摘要（免 LLM 判定表）

按序命中即用规则摘要（写入 f.summary，与 LLM 摘要同待遇进缓存/嵌入）：

| 规则 | 判定 | 摘要模板 |
|---|---|---|
| 测试文件 | 路径含 `test/`/`__tests__/` 或名含 `.test.`/`.spec.`/`test_` 前缀 | "X 的测试用例，覆盖：<top 符号>" |
| 类型定义 | `.d.ts`，或 ts 文件符号全为 interface/type/enum | "类型定义：<符号清单>" |
| 纯导出 barrel | 仅 import/export 语句（module 块外无定义） | "聚合导出：<导出来源清单>" |
| 常量/配置 | 符号全为大写常量或文件名 config/constants | "配置常量：<符号清单>" |
| 小文件 | 总行数 <30 | "<符号签名拼接>" |

其余走 LLM。stats 增 `summaries_rule` 计数。判定实现于 summarizer 侧新函数 `rule_summary(file, chunks) -> str | None`，单测覆盖每条规则。

### D6: L2 输入分级

LLM 路径的输入按文件规模分档：<100 行 → 只给符号签名（省 head）；100-400 行 → head 300 字符 + 符号 800；>400 行 → 现行满额。纯 prompt 组装改动。

### D7: 深度模式 = 管道跳段 + 状态可补跑

- `POST /projects/{id}/index?depth=fast|deep`（默认 deep），Project 表加 `index_depth` 列记录最近深度
- fast：summarize 阶段全部走规则摘要（L3 用文件清单模板、L4 用路由地图模板，零 LLM），report 阶段只生成程序化两件（顶层导图 + 数据流图），跳过文档与时序图（置空并标 `depth: fast`）
- 详情页「生成深度理解」按钮 → `POST /projects/{id}/index?depth=deep&mode=auto`：无代码变更时摘要/嵌入全缓存命中，只补 LLM 摘要与报告（增量机制天然支持）
- 前端报告页在 fast 报告上显示"快速模式产物，点击生成深度理解"引导

## Risks / Trade-offs

- [规则摘要误判业务文件] → 判定条件保守（全符号匹配才命中），误判也只是摘要略糙，检索主力仍是代码嵌入
- [数据流图在强耦合项目边过多] → 弱边（<2）省略 + 边数上限 60，超限按权重截断并标注
- [fast 模式检索质量下降] → 规则摘要仍提供文件级语义 + 代码嵌入不打折；引导按钮明示可升级
- [文档分批后章节风格不一致] → 批内 prompt 带统一格式约定；概述章节收口

## Migration Plan

alembic 0003：understanding_reports 加 dataflow_mermaid（nullable）、projects 加 index_depth（默认 deep）。旧报告 dataflow 为空时前端隐藏该卡片。

## Open Questions

（无）
