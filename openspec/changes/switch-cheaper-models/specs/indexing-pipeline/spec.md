## MODIFIED Requirements

### Requirement: 嵌入向量化
embed 阶段 SHALL 调用配置指定的 OpenAI 兼容嵌入服务（供应商、模型与维度均由环境变量 `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` 控制，规格不绑定任何具体供应商）对块的嵌入文本批量向量化（批大小 10），并发受限且对限流/超时按指数退避重试。相同 `(project_id, content_hash)` 的块 SHALL 复用已有向量，不重复调用 API。请求 SHALL 显式下发 `dimensions` 参数，使配置的维度与服务端实际返回维度一致。

#### Scenario: 断点续跑不重复计费
- **WHEN** 上次任务在 embed 阶段中断后重新触发索引
- **THEN** 已嵌入过（content_hash 未变）的块直接复用向量，仅新块调用嵌入 API

#### Scenario: 限流退避
- **WHEN** 嵌入 API 返回限流错误
- **THEN** 按指数退避重试，最终失败则任务 failed 并记录 error_text

#### Scenario: 更换嵌入供应商
- **WHEN** 仅 `EMBEDDING_BASE_URL` 与 `EMBEDDING_MODEL` 改变而 `EMBEDDING_DIM` 不变
- **THEN** 嵌入调用改向新服务，且因模型标识变化触发全量重嵌入，不产生新旧模型向量混存

## ADDED Requirements

### Requirement: 嵌入模型变更的迁移语义
更换嵌入模型或维度 SHALL 被当作一次数据迁移而非配置调整：系统 MUST NOT 让不同模型或不同维度产生的向量共存于同一项目的检索空间。项目图中 SHALL 记录产出其向量的 `embedding_model` 与 `embedding_dim`；索引时若二者与当前配置不符，SHALL 放弃增量路径、强制全量重嵌入并记录原因。维度与既有向量索引冲突时，后端 SHALL 拒绝启动并给出需重建的索引名，MUST NOT 静默改用不匹配的索引。

#### Scenario: 模型标识变化触发全量重嵌入
- **WHEN** 项目图中记录的 `embedding_model` 或 `embedding_dim` 与当前配置不一致，且该项目已有索引产物
- **THEN** 本次索引放弃增量路径、走全量重嵌入，并在任务统计中记录回退原因为嵌入模型变化

#### Scenario: 维度与既有索引冲突时拒绝启动
- **WHEN** 启动时任一向量索引的既有维度与 `EMBEDDING_DIM` 不符
- **THEN** 后端启动失败，错误信息指明冲突的索引名、两侧维度与重建方法

#### Scenario: 迁移后质量以指标验收
- **WHEN** 完成嵌入模型更换与全量重索引
- **THEN** 以既有检索评测 harness 在相同评测集上产出指标，与更换前基线可比，指标低于既定门槛时按回滚路径还原
