# M17 任务清单

分组即派工单元：组 1/2 一个包（测试基建+CI），组 3 一个包（检索评测），组 4 一个包（存储演练），可两会话并行——组 3、4 互不相交；组 1 是两者的公共前置（先做）。组 5/6 由 PM 会话收尾。

## 1. 测试基建与安全护栏

- [x] 1.1 dev 依赖加入 pytest-cov / pytest-timeout / pytest-socket，pyproject 配置全局超时 120s（integration marker 放宽至 300s）
- [x] 1.2 conftest 最早阶段以 `_env_file=None` 重建 settings 并注入哑凭据，保证任意 CWD 启动测试都不加载真实 `.env`；补一条「从仓库根跑也安全」的自证测试
- [x] 1.3 单测档启用禁外网（允许 localhost/127.0.0.1），集成档不启用
- [x] 1.4 集成测试增加服务可达性探测 fixture：Neo4j / MinIO 不可达时 skip 带原因，替换现有直接连接报错行为
- [x] 1.5 FakeLLM / make_tree 等共享夹具从 test_report.py 下沉到 tests/helpers，消除 test_business_flows / test_feature_groups / test_feature_map 的跨文件 import
- [x] 1.6 单测档全量跑通并实测覆盖率，`fail_under` 写死为实测值向下取整

## 2. CI 工作流

- [x] 2.1 新增 `.github/workflows/ci.yml`：unit job（push+PR，uv 环境，`-m "not integration"` + 覆盖率门槛 + 超时）
- [x] 2.2 同工作流 integration job（main push 触发；service 容器起 Neo4j 5.26-community（NEO4J_PLUGINS=apoc）与 MinIO，健康检查就绪后跑 `-m integration`）
- [ ] 2.3 推送验证两 job 真实绿灯；故意引入一个失败提交验证红灯可见后还原

## 3. 检索评测基线

- [x] 3.1 标注 golden 评测集（≥20 条，local/global/impact 三类覆盖，query → 期望 node_id/文件+行号），必要时扩充 mini_repo；数据文件格式可读可评审
- [x] 3.2 `_index_fixture` 从 test_pipeline_integration 提升为可复用建图 helper（空 Neo4j 一键建图）
- [x] 3.3 实现指标 harness：直调 `search_layered`，计算 hit@k / recall@k / MRR，输出按 query 明细+汇总，报告头部含配置指纹（top_k、rerank 开关等）
- [x] 3.4 离线确定性档：fake 向量 + rerank 关闭，生成并提交基线快照（按 question_type 分文件，钉 node_id 序列不钉分数）；快照比对用例进 CI；提供显式重建快照命令
- [ ] 3.5 真实模型评测脚本 `backend/scripts/eval_retrieval.py`（真 embedding + 可选 rerank，手动触发），跑通一次并把首个质量基线数（含日期/模型/配置指纹）记入 `docs/`

## 4. 存储硬化与故障演练

- [x] 4.1 硬化一：`export_bundle` 产包后 `git bundle verify`，失败不上传、保留远端旧包、warning 入 stats；配套用例（坏包不覆盖好包）
- [x] 4.2 硬化二：`Minio()` 显式超时 http_client（连接/读秒级，配置项含默认值）；配套用例（挂起在超时上限内降级）
- [x] 4.3 端到端 bundle 生命周期用例（目录假存储，进单测档）：首索引产 bundle → 二次索引从 bundle 恢复 → 断言 `stats.code_source` 为 bundle 来源且增量正确
- [x] 4.4 故障矩阵用例补齐：MinIO 不可达、bundle 损坏、上传失败、worker 首传时桶不存在、`_bucket_ready` 失败后自愈
- [x] 4.5 真 MinIO 集成用例（integration 档）：桶惰性初始化、bundle 上传下载往返、超时行为，吃 CI 的 MinIO 容器

## 5. 规格与文档收尾

- [x] 5.1 M10 孤儿 change 归位：`backend/openspec/changes/m10-answer-latency` 移入 `openspec/changes/archive/2026-08-14-m10-answer-latency/`，顶部注明「delta 已由 M17 按现行 spec 结构补录」
- [x] 5.2 README「当前进度」更新（仍写 M4）、测试章节补 CI 与评测跑法；docker-compose repos 卷注释改为 M16 后语义（任务级临时区）
- [x] 5.3 `.env.example` 补 MinIO 超时配置项说明（提交前 grep 检查无真实 key）

## 6. 验收（PM）

- [ ] 6.1 主观验收：CI 两 job 绿灯截图/链接；故意漂移一次检索顺序确认离线档红灯
- [ ] 6.2 核对四份 spec delta 场景逐条有对应用例或脚本产出
- [ ] 6.3 真实档基线数已入 docs 且含配置指纹；`openspec status` 全勾后归档
