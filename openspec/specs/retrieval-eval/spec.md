# retrieval-eval Specification

## Purpose
检索质量评测能力：维护基于固定 fixture 仓的 golden 评测集，提供直接调用检索服务层的指标 harness（hit@k / recall@k / MRR，含配置指纹），以离线确定性快照档进入 CI 拦截检索行为漂移，并以真实模型评测档手动建立质量基线（M17）。

## Requirements

### Requirement: golden 评测集
仓库 SHALL 维护一个标注检索评测集：基于固定 fixture 仓（mini_repo，必要时扩充），每条记录含 query、question_type（local/global/impact）与期望命中（文件粒度；模块摘要按模块名匹配——node_id 含起始行号，代码微调即失效，文件粒度足以判定「有没有找对地方」）；规模 SHALL 不少于 20 条且三类问题均有覆盖。评测集变更 SHALL 经代码评审（纯数据文件，diff 可读）。

#### Scenario: 评测集可复现建图
- **WHEN** 在空 Neo4j 上运行评测 harness
- **THEN** harness 自动索引 fixture 仓并完成全部评测，无任何手工准备步骤

### Requirement: 检索指标 harness
系统 SHALL 提供评测 harness：直接调用检索服务层 `search_layered`（不经 HTTP、不经问答 LLM），对评测集逐条计算 hit@k、recall@k 与 MRR，输出按 query 的明细与汇总均值；运行时 SHALL 显式固定检索配置（top_k、rerank 开关等）并在报告头部输出配置指纹，保证跨次运行可比。

#### Scenario: 指标输出可比
- **WHEN** 以相同配置对相同评测集运行两次 harness
- **THEN** 两次报告的配置指纹一致，离线档指标完全一致

### Requirement: 离线确定性回归档
CI SHALL 运行离线评测档：使用确定性 fake 向量、rerank 关闭，断言各 query 检索返回的 node_id 序列与已提交的基线快照一致；SHALL NOT 断言分数值。检索行为变化导致的不一致 SHALL 使 CI 失败；基线更新 SHALL 通过显式命令重新生成快照文件并随 PR 评审。

#### Scenario: 检索行为漂移被拦截
- **WHEN** 一次改动使某 query 的 top-k node_id 顺序发生变化
- **THEN** CI 离线档失败，报告中列出漂移的 query 与前后序列对比

#### Scenario: 分数尺度变化不误报
- **WHEN** 仅 score 数值因内部实现调整而变化、node_id 序列不变
- **THEN** 离线档通过

### Requirement: 真实模型评测档
系统 SHALL 提供手动评测脚本：以真实 embedding（可选开启 rerank）运行同一评测集，产出指标报告；首次运行结果 SHALL 连同日期、模型名与配置指纹记录为质量基线文档。该档 SHALL NOT 进入 CI 自动运行。

#### Scenario: 手动建立质量基线
- **WHEN** 维护者手动运行真实模型评测脚本
- **THEN** 产出含配置指纹的指标报告，基线文档记录本次数值供后续对比
