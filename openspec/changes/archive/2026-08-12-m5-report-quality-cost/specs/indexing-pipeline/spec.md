# indexing-pipeline — 摘要成本分级与深度模式（M5）

## MODIFIED Requirements

### Requirement: 四层摘要生成
索引管道 SHALL 在 summarize 阶段生成三级摘要（与 L1 代码块合为四层理解）。L2 文件摘要 SHALL 先经**规则分级判定**，命中者以确定性规则摘要免 LLM 生成：测试文件（路径/文件名特征）、类型定义文件（.d.ts 或符号全为类型声明）、纯导出 barrel 文件、常量配置文件、总行数 <30 的小文件；规则摘要与 LLM 摘要同等进入缓存与嵌入。未命中者走 LLM，且输入按文件规模分级（<100 行仅符号签名；100-400 行减量头部与符号；更大者满额）。L3 模块摘要（输入为模块内 L2+路由入口）与 L4 项目总览机制不变。L2 按文件 content_hash 缓存、L3 按模块文件 hash 聚合缓存；单条摘要失败退避重试 3 次后降级符号清单占位并标 partial。stats SHALL 记录 summaries_rule（规则摘要数）与 summaries_new/summaries_cached。

#### Scenario: 规则文件免 LLM
- **WHEN** 索引含测试文件、.d.ts 类型文件与纯导出 index.ts 的项目
- **THEN** 这些文件获得规则摘要（内容含符号/来源清单），不产生 LLM 调用，stats.summaries_rule 相应计数

#### Scenario: 摘要缓存生效
- **WHEN** 对内容未变化的项目再次全量索引
- **THEN** L2/L3 摘要不产生新的 LLM 调用

#### Scenario: 摘要失败降级
- **WHEN** 某业务文件摘要调用连续失败
- **THEN** 该文件以符号清单占位，任务完成且标记 partial

## ADDED Requirements

### Requirement: 索引深度模式
索引 SHALL 支持 depth=deep|fast（默认 deep）。fast 模式下 summarize 阶段全部使用规则/模板摘要（L2 规则或符号清单、L3 文件清单模板、L4 路由地图模板，零 LLM 调用），report 阶段仅生成程序化产物（顶层导图与数据流图），文档与时序图置空并在报告标记 depth=fast；路由地图、图结构、代码块嵌入与检索能力 MUST 与 deep 模式一致。项目记录最近索引深度；fast 项目可通过 depth=deep 的 auto 索引补跑深度理解（未变更内容走缓存，仅补 LLM 摘要与报告）。

#### Scenario: fast 模式零 LLM 录入
- **WHEN** 以 depth=fast 索引一个新项目
- **THEN** 任务成功且 summarize/report 阶段 LLM 调用数为 0，代码检索与功能地图正常可用

#### Scenario: fast 升级 deep 只补差价
- **WHEN** fast 索引过的项目在无代码变更时以 depth=deep 触发 auto 索引
- **THEN** 嵌入全部缓存复用，仅产生 LLM 摘要与报告生成调用，完成后报告为完整深度版
