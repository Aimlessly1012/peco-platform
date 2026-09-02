# M17 设计 — 测试与回归基线

## Context

M15/M16 重写了检索链与存储层后，仓库有 584 个测试用例（38 文件平铺，仅 `integration` 一个 marker）但零 CI、零覆盖率工具、零质量指标。三处关键空洞：

1. **检索质量无可判定基线**：唯一「问题集」是 `test_pipeline_integration.py` 里 3 条硬编码冒烟问题，跑 fake 词袋向量，只断言命中文件；spec 全是机制性 SHALL，没有任何数值验收线。
2. **bundle 端到端路径零测试**：conftest 不配 MinIO，`storage_enabled()` 恒 False，所有 pipeline 集成测试只走 clone 路径；「首索引产 bundle → 二次索引从 bundle 恢复」从未被自动化验证。
3. **测试环境有真实风险**：从仓库根跑 pytest 会加载根 `.env`（含真实 API key）可能真打计费接口；集成测试在 Neo4j 未起时直接报错而非 skip；无超时，挂死用例卡整轮。

现成的有利条件：`search_layered(project_id, query, question_type, top_k)` 是干净的独立异步入口（spec 已有「检索服务层独立可调用」要求）；`tests/fixtures/mini_repo` 是现成 golden corpus 底座；`_index_fixture` helper 已能绕过 git 阶段建图。

## Goals / Non-Goals

**Goals:**
- 每次 push/PR 有自动红绿灯（CI 单测档），检索行为漂移与覆盖率下跌可被拦截。
- 检索质量有首个数值基线（真实模型档，手动）与确定性结构基线（离线档，进 CI）。
- bundle 全生命周期与故障矩阵有自动化用例；两项真风险（坏包覆盖好包、MinIO 挂起阻塞）被修复。
- 测试环境安全：误操作不打计费 API，依赖缺失 skip 而非报错。

**Non-Goals:**
- 不改检索链与问答 API 的任何线上行为（两项硬化只改失败路径）。
- 不做真 Postgres/RabbitMQ 集成档、MinIO 对象生命周期（删项目清桶）、bundle 新鲜度巡检、远端不可达的离线索引模式、问题分类（understand 节点）准确率评测、前端测试——全部记 M18 候选。
- 不追覆盖率高门槛，只记录基线并防跌。

## Decisions

**D1 评测双层：离线确定性档进 CI，真实模型档手动跑。**
fake 词袋向量（conftest 现有 `fake_embed`）无语义能力，只能证明「检索管线结构没变」；真实召回质量必须用真 embedding（+rerank）。二者合一会让 CI 既贵又不确定。故离线档做 CI 门禁（确定性、零费用），真实档做质量基线（手动触发、记录数值与模型版本、模型侧变更时重跑）。备选「只做真实档」被否：每次 push 产生费用且云端模型漂移会让红灯不可信。

**D2 离线基线钉 node_id 集合与顺序，不钉分数。**
`RetrievedItem.score` 在管线中被覆写三次（cosine → RRF → rerank），钉分数值等于钉实现细节，切换 rerank 配置即全红。离线档固定 rerank 关闭（rerank 是外部 API，离线本就不可用），断言 top-k node_id 序列与快照一致；基线更新是显式动作（重新生成快照文件，diff 进 PR 可审）。

**D3 harness 挂 `search_layered`，不走 HTTP、不走 qa_graph。**
直调检索服务层无需 FastAPI/登录态/聊天 LLM，`question_type` 显式传参（local/global/impact 各自覆盖）。qa_graph 全链路有已知坑（generate_node 不把答案写进 state，必须拼流事件）且引入 LLM 不确定性，不适合做检索指标。指标取 recall@k、hit@k、MRR，按 query 出明细、汇总出均值；运行时显式固定 `retrieval_top_k` 与 rerank 三项配置，报告头部打印配置指纹保证可比。

**D4 评测集：扩展 mini_repo 为标注 golden corpus。**
在 `tests/fixtures/mini_repo`（必要时适度扩文件）上标注 ≥20 条 query → 期望命中（node_id 或文件+行号区间），覆盖 local/global/impact 三类。评测 harness 复用 `_index_fixture` 思路自动建图（该 helper 从私有提升为可复用），空 Neo4j 上一条命令跑通、无手工步骤。备选「用真实大仓做评测集」被否：不可复现、标注成本高，留给真实档在服务器上按需做。

**D5 CI：GitHub Actions 两 job。**
- `unit`：push + PR 触发，无外部服务，`uv run pytest -m "not integration"` + 覆盖率 + 超时。
- `integration`：起 Neo4j（5.26-community，`NEO4J_PLUGINS=apoc`）与 MinIO service 容器，跑 `-m integration`。
覆盖率用 pytest-cov，`fail_under` 取首次实测值向下取整（防跌 ratchet，人工上调）。新增 dev 依赖：pytest-cov、pytest-timeout、pytest-socket。超时全局 120s，integration 档放宽（marker 级覆盖）。

**D6 测试安全护栏两道。**
① conftest 在最早阶段以 `_env_file=None` 重建 settings 并注入哑 key，使「从任何 CWD 跑测试」都不加载真实 `.env`；② 单测档用 pytest-socket 禁外网（允许 localhost），集成档放行本地服务端口。集成用例增加服务可达性探测 fixture，不可达时 `pytest.skip` 带原因。备选「只靠 README 提醒 cd backend」维持现状被否：已知真风险不能靠纪律防。

**D7 bundle 端到端与故障矩阵分两档。**
端到端用例（首索引产 bundle → 二次索引恢复 → 断言 `stats.code_source == 'bundle'` 与增量正确）用现有目录假存储模式跑进单测档（确定性、无服务）；真 MinIO SDK 往返（桶惰性初始化、上传下载、超时行为）进集成档吃 CI 的 MinIO 容器。故障矩阵：MinIO 不可达、bundle 损坏、上传失败、worker 首传桶不存在、`_bucket_ready` 失败后自愈。

**D8 两项硬化的实现口径。**
① `export_bundle` 产包后先 `git bundle verify`，失败则不上传、保留远端旧包、记 warning 入 stats——坏包永不覆盖好包；② `Minio()` 显式传入带连接/读超时（秒级，配置项给默认值）的 http_client，挂起场景在限定时间内走既有降级路径（下载失败→回退 clone，上传失败→warning）。均不改成功路径。

**D9 M10 孤儿 change 的归位方式：按现行 spec 结构补录，不机械 sync。**
`backend/openspec/changes/m10-answer-latency` 的 delta 用的 requirement 标题（「分层混合检索」「流式问答」）与现行主 spec 对不上，无法直接 sync。处置：M17 的 code-chat delta 以现行结构补录其内容（上下文预算裁剪、模型分流两条 ADDED），孤儿目录整体移入 `openspec/changes/archive/2026-08-14-m10-answer-latency/` 并在其 README/顶部注明「delta 已由 M17 按现行 spec 结构补录」。同时修正 citations 口径：主 spec「引用契约」场景写了 score，实现与契约测试是七字段无 score——以实现为权威修 spec 文本。

## Risks / Trade-offs

- [离线快照基线脆：改 chunker/fixture 会成片红] → 基线更新是单条显式命令重新生成快照，diff 随 PR 可审；快照按 question_type 分文件，缩小爆炸半径。
- [CI 集成档 Neo4j 启动慢或插件拉取不稳] → healthcheck 重试拉满（本地 compose 已 retries 30 可参照）；集成档失败不掩盖单测档信号（两 job 独立）。
- [真实档基线数受云端模型不可控变更影响] → 报告记录日期、模型名与配置指纹；数值异动先查模型侧公告再查代码。
- [pytest-socket 禁网误伤本地组件] → 允许 localhost/127.0.0.1;集成档不启用禁网。
- [覆盖率 ratchet 初值过低失去意义] → 初值如实记录即可，M17 目标是「有基线可对比」，不是冲高。
- [七字段口径以实现为权威可能掩盖真实需求（前端要不要 score）] → 前端引用卡片现只用路径/行号/预览，不消费 score；若未来要显示相关度，再走正式 change 加字段。

## Migration Plan

全部为增量新增（CI、评测、用例）+ 两处小硬化。无数据迁移。回滚：硬化各自单 commit，可独立 revert；CI 工作流删除文件即回滚。上线不涉及服务器部署动作（评测真实档在服务器跑时另行遵守部署纪律：跑前查 indexing 中任务）。

## Open Questions

- 覆盖率初始 `fail_under` 具体数值：实施时以首次实测为准（预计 70%+，实测后写死）。
- 评测集最终规模与三类问题配比：实施时以 mini_repo 可标注密度为准，下限 20 条；不足则先扩 fixture 再标注。
