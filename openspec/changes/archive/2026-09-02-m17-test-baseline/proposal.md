# M17 测试与回归基线

## Why

M15（检索链 LangChain 化）与 M16（git bundle 主存储）刚重写了系统最核心的两层，但全仓库没有 CI、没有检索质量指标、没有 bundle 端到端用例——「回归」目前没有可判定的失败条件：584 个测试用例全靠本地手跑，检索质量只有机制断言没有数值基线，M16 的 bundle 恢复路径从未被自动化验证过（conftest 不配 MinIO，所有集成测试只走 clone 路径）。趁架构进入稳定窗口，建立「改完没变差」的可判定回归基线。

## What Changes

- **CI 回归门禁**：新增 GitHub Actions 工作流——单测档（无外部服务）+ 集成档（起 Neo4j）；引入 pytest-cov / pytest-timeout，记录覆盖率基线（只记录与防跌，不设高门槛）。
- **测试安全护栏**：conftest 兜底防止从仓库根跑测试误加载真实 `.env` 打计费 API；集成测试在 Neo4j 不可达时自动 skip 并给出原因（当前是直接报错）。
- **检索质量评测基线**：建 golden 问题集（标注 query → 期望命中 node_id/文件），recall@k / MRR 指标 harness 挂在 `search_layered` 独立入口上；分两档——离线确定性档（fake 向量，钉 node_id 集合与顺序、不钉分数）进 CI，真实模型档（真 embedding + rerank）手动触发、记录首个质量基线数。
- **存储层故障演练**：bundle 全生命周期集成用例（首次索引产 bundle → 二次索引从 bundle 恢复 → 增量，断言 `stats.code_source == 'bundle'`）；故障矩阵用例（MinIO 不可达、bundle 损坏、上传失败、worker 首传时桶不存在）。
- **两项低风险硬化**（演练暴露的真风险，随本里程碑修）：bundle 上传前 `git bundle verify` 自校验，坏包不覆盖好包；MinIO 客户端显式超时，服务挂起不再让索引任务阻塞分钟级。
- **测试工位整理**：`FakeLLM` / `make_tree` 等共享夹具从 `test_report.py` 下沉到 `tests/helpers`，消除三个文件的跨文件 import 耦合。
- **规格收尾**：将遗留在 `backend/openspec/changes/m10-answer-latency` 的孤儿 change 归位归档，其已上线需求（上下文预算裁剪、GENERATE_MODEL 分流）补录进主 spec；修正 `code-chat` spec 中 citations 字段口径与实现（七字段、无 score）的不一致；README 进度与 compose repos 卷注释更新为 M16 后语义。

**不做**（记入 M18 候选）：真 Postgres 集成档（sqlite 替身的方言盲区）、MinIO 对象生命周期（删项目清桶）、bundle 新鲜度巡检与告警、远端不可达时的 bundle 离线索引模式、前端测试。

## Capabilities

### New Capabilities

- `regression-testing`: 回归测试门禁——CI 工作流（单测/集成两档）、覆盖率基线与防跌、测试超时、测试环境安全护栏（.env 隔离、集成依赖不可达自动 skip）。
- `retrieval-eval`: 检索质量评测基线——golden 问题集、recall@k / MRR 指标 harness、离线确定性档（CI 门禁）与真实模型档（手动、记录基线数）的双层评测。

### Modified Capabilities

- `artifact-storage`: 新增两条 requirement——bundle 上传前自校验（verify 失败不覆盖远端旧包）；MinIO 客户端显式超时（挂起在限定秒数内降级）。bundle 恢复路径补充可验证场景（端到端 code_source 断言）。
- `code-chat`: 补录 M10 已上线需求（`CONTEXT_CHAR_BUDGET` 上下文预算裁剪与 `context_min_items` 底线、`GENERATE_MODEL` 生成模型分流）；修正「流式回答与引用」中 citations 字段口径为实现实际的七字段契约（file_path/start_line/end_line/node_id/symbol/kind/via_edge，不含 score）。

## Impact

- **代码**：`backend/tests/**`（新增评测 harness、故障演练用例、helpers 下沉）、`backend/pyproject.toml`（dev 依赖与 pytest 配置）、`.github/workflows/`（新增）、`backend/app/services/storage/minio_client.py` 与 `backend/app/services/ingest/git_ops.py`（两项硬化，改动很小）、`backend/scripts/`（真实模型评测脚本，新目录）。
- **行为红线**：检索链与问答 API 的线上行为零变化；两项硬化只改失败路径（verify 失败、超时降级），成功路径不动。
- **规格**：主 spec 两处修订（artifact-storage、code-chat），M10 孤儿 change 迁移归档。
- **成本**：真实模型评测档每次跑产生少量 embedding/rerank API 费用，仅手动触发，不进 CI。
- **依赖**：CI 依赖 GitHub Actions（仓库已在 GitHub）；集成档在 CI 中起 Neo4j 容器。
