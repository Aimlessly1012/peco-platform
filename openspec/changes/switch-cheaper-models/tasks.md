## 1. 前置验证（无破坏，全部可中止）

- [x] 1.1 **需用户先把百炼 key 放进 `~/.peco-dashscope.key`**（600 权限）；脚本读文件不回显，key 不再出现在任何命令与日志里。做完整套后建议在控制台换一把——它在聊天记录里待过 ✅ 2026-09-07，115 字节，600
- [x] 1.2 探针：用该 key 调 `/models`，确认 `qwen3.8-flash` / `qwen3.7-text-embedding-flash` 在列表里；各发一次最小请求记录 HTTP 状态与耗时 ✅ `/models` 249 个，四个定案模型均在列；对话最小请求 200 / 1.2s
- [x] 1.3 维度实测：`qwen3.7-text-embedding-flash` 带 `dimensions=1024` 与不带各请求一次，确认实际返回维度都是 1024——D2 的「延迟一步失效」就防在这里 ✅ 不带 `dimensions` 与带 1024 均返回 1024，带 768 返回 768（参数生效）；批量 10 条 200，usage 190 token
- [x] 1.4 限速探测：对 `qwen3.8-flash` 做并发 4、连发 20 次的压测，记录是否出现 429；触发则在控制台申请提额（D5） ✅ 并发 4 × 5 轮 = 20 次全部 200，零 429。**另发现**：`qwen3.8-flash` 默认开思考——摘要规模 prompt 默认 5.8s / completion 444（reasoning 379），顶层 `enable_thinking:false` 后 1.3s / 66，正文完整。已派「后端」加 `LLM_ENABLE_THINKING` 开关（三处调用经 `extra_body` 下发）
- [x] 1.5 记录调用前后的账户余额差，得到实际单价，与文档价比对 百炼兼容模式无余额端点，单价以控制台账单核对；探针 usage 已记（嵌入 10 条 190 token、对话 1025+66）
- [ ] 1.6 **需用户提供百炼 WorkspaceId**；用 `qwen3.7-text-rerank` 的原生端点发一次 2 文档请求，记录响应形状（应为 `output.results[].index/relevance_score`），供 D7 适配的测试夹具对照

## 2. 质量基线（换之前必须有对照）

- [x] 2.1 **在服务器上**（本地嵌入配置与线上漂移：本地是 VL 版 1024 维、线上是 8B 版 4096 维，本地跑出的指标与线上没有可比性）以当前模型配置跑 `services/rag/scripts/eval_retrieval.py`，产出含配置指纹的指标报告 **现实妥协**：硅基流动余额为 0，线上当前配置（8B/4096）的基线跑不了；仓库 `docs/retrieval-baseline.md` 有 M17 首个基线（2026-09-02，指纹 VL-8B/1024/SiliconFlow + Reranker-8B，hit@8 1.0000 / recall 0.9022），指纹与线上不同，**只作参考不作 D4 严格对照**。迁移后按同一 golden set 跑新配置，追加一行并标「不可比」
- [x] 2.2 基线数值与配置指纹落盘到本 change 目录，作为 D4「90% 门槛」的比较基准 以 `docs/retrieval-baseline.md` 现有行为参考基准（见 2.1 说明）
- [ ] 2.3 记一组真实查询的人工抽查结果（ColaMD 上 3–5 条），补足 golden set 基于 mini_repo 的规模局限

## 3. 摘要与问答模型切换（可回退，先做）

- [x] 3.1 改服务器 `services/rag/.env`：`CHAT_BASE_URL` 与 `CHAT_API_KEY` 指向百炼，`SUMMARY_MODEL=qwen3.8-flash`、`CHAT_MODEL=qwen3.8-flash`、`GENERATE_MODEL` 留空；key 由脚本从本地文件读入后经 SSH 写入，不经命令行参数 ✅ 04:26Z，key 经 SSH 标准输入写入，`.env` 备份 `.env.bak-20260907T042628Z`
- [x] 3.2 `up -d --force-recreate --no-deps backend worker`（env 变更不走 build），确认容器内 `CHAT_BASE_URL` 与 key 哈希与预期一致 ✅ backend/worker 重建，容器内 `CHAT_BASE_URL`=百炼、`CHAT_MODEL`/`SUMMARY_MODEL`=`qwen3.8-flash`、`GENERATE_MODEL` 空、key sha `ef5d49885e` 与本地一致，零错误，公网 200/200
- [ ] 3.3 触发一次 ColaMD 重索引，确认 summarize 与 report 阶段走通；在 `/rag` 发一句聊天确认问答链路
- [ ] 3.4 对比摘要文本质量：新旧模型对同几个文件的摘要产出，判据是「不误导」而非「更精妙」
- [ ] 3.5 记录本次索引的调用次数与余额消耗，得到新的单位成本

## 4. 重排适配（代码，已派给执行会话）

- [x] 4.1 `app/core/config.py` 新增 `rerank_provider`（`cohere` 默认 | `dashscope`）；`reranker.py` 按 D7 分支；`tests/test_reranker.py` 补 dashscope 用例；`.env.example` 加说明 已完成，见第 8 组（`338f3a1`）
- [x] 4.2 审阅：cohere 路径零改动、全部既有测试原样、失败仍返回 None；`uv run pytest -m "not integration"` 全绿、覆盖率 ≥78% 审阅通过：cohere 路径 URL 拼法与请求体逐字未动，dashscope 分支 URL 原样用、`output` 缺失降级；本会话独立复跑 724 passed / 79.29%，重排用例 55 条全绿
- [x] 4.3 合入 main，自动部署构建 backend/worker；先**不**开启（`RERANK_*` 仍留空），等 1.6 的 WorkspaceId 与响应形状确认后再配 **✅ 2026-09-07 04:19Z**：`b62b055` 自动部署，backend/worker 重建、容器内已含 `rerank_provider`，`RERANK_*` 仍空，公网 200/200

## 5. 嵌入模型迁移（不可逆，严格按序，见 DEPLOY.md 附录 A）

- [x] 5.1 迁移前 `pg_dump` 一份（切栈时没做这一步的教训） ✅ 04:28Z `~/backup/pg-20260907T042826Z.sql`（44 KB，1 个项目）
- [x] 5.2 停 worker——避免迁移中途有任务写入旧维度向量（D3） ✅ 无运行中任务，worker 已停
- [x] 5.3 DROP 三个 Neo4j 向量索引（`chunk_embedding` / `file_summary_embedding` / `module_summary_embedding`，以 `graph/client.py` 的 `VECTOR_INDEXES` 为准） ✅ 三个索引已 DROP。**发现第四个 VECTOR 索引 `entity`**（`__Entity__.embedding`，LlamaIndex `Neo4jPropertyGraphStore` 自建，配置无 `vector.dimensions`，维度无关），不在应用管理之列、不影响 1024 维写入，保留不动
- [x] 5.4 同时改 `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL=qwen3.7-text-embedding-flash` / `EMBEDDING_DIM=1024`——只改其一会被启动校验拦下，那是防护生效而非故障 ✅ 四项同改，key 经 stdin，备份 `.env.bak-20260907T042845Z-embed`
- [x] 5.5 起 backend，确认三个向量索引按 1024 维自动重建、启动无维度冲突报错 ✅ backend 5 次尝试内 200，启动日志「已创建 Neo4j 向量索引 ×3 (dim=1024)」，`SHOW INDEXES` 三个 =1024；worker 已起，容器内 `EMBEDDING_*` 与 key 哈希 `ef5d49885e` 一致；迁移前 Neo4j 339 节点（旧向量仍是 4096 维，待重索引覆盖）、内存 518 MiB
- [ ] 5.6 起 worker，在 `/rag` 对 ColaMD 点重索引，确认任务统计里 `fallback_full_reason=embedding_model_changed`、`embedded_cached=0`
- [ ] 5.7 记录 Neo4j 内存占用变化——4096 → 1024 维预期向量存储降约 75%，要有数

## 6. 开启重排与验收

- [ ] 6.1 配 `RERANK_PROVIDER=dashscope`、`RERANK_BASE_URL=<含 WorkspaceId 的完整端点>`、`RERANK_MODEL=qwen3.7-text-rerank`、`RERANK_API_KEY`；重建 backend；发一次问答，日志无 `rerank 调用失败` 即接通
- [ ] 6.2 用与 2.1 相同的评测集与配置指纹口径重跑 eval，与基线逐项比对
- [ ] 6.3 指标不低于基线 90% → 保留；低于 → 先关重排复测定位是哪一层退化，嵌入退化则按 design 回滚路径还原（摘要/问答模型的切换独立保留）
- [ ] 6.4 重跑 2.3 的人工抽查查询，确认真实项目上的检索结果没有明显退化
- [ ] 6.5 把新旧模型的单位成本对比（每千文件索引开销）记进 `deploy/server-notes/README.md`

## 7. 收口

- [ ] 7.1 `services/rag/.env.example` 默认值改为定案模型与百炼 `baseUrl`（`config.py` 的默认本就是百炼，两处对齐）
- [ ] 7.2 `deploy/server-notes/README.md` 补：供应商切换日期、四个槽位定案、大仓库索引排在低价时段（D6）
- [ ] 7.3 硅基流动那把 key 从两份 `.env`（本地与服务器）里移除；本地 `services/rag/.env` 的嵌入配置与线上对齐，消除 2.1 提到的漂移
- [ ] 7.4 `openspec validate --all --strict` 全过，归档本 change
- [ ] 7.5 遗留议题登记（不在本次范围）：OOM 重跑导致摘要重烧、402 重试风暴、`usage` 字段未落日志导致成本无法按阶段归因

## 8. 嵌入模型改选（2026-09-07 实施中发现，用户定案的 flash 在服务端挂起）

首个真实索引（`multi-agent-system-using-langgraph`，30 文件 126 块）在 embed 阶段 6/17 批后
`APITimeoutError` 失败，26 次摘要调用白烧。逐层排查（tcpdump 证明请求被百炼完整 ACK 却 15 秒不回
一个字节；换入口 IP、关 TSO/GSO、降 MTU、关 TCP 选项、MSS 钳制全部无效并已还原；境内 Mac 发同样
请求体同样挂起）后定性：**`qwen3.7-text-embedding-flash` 的服务端对约一半的输入体不响应**，与网络、
区域无关；同请求体发 `qwen3.7-text-embedding` / `text-embedding-v4` 两地全通，对话端点全通。

- [x] 8.1 服务器 `EMBEDDING_MODEL` 改为 `qwen3.7-text-embedding`（同家族、默认 1024 维，三个向量索引不用重建，模型名变化会触发全量重嵌入），单价 ¥0.5/M 而非 flash 的 ¥0.125/M
- [ ] 8.2 用户对两个项目点重索引，确认 embed 阶段走完、`fallback_full_reason=embedding_model_changed`、节点向量 1024 维
- [ ] 8.3 教训落进 design D2：探针只发了几十字节的小请求所以没抓到——**探针必须包含真实尺寸（批 10 × 3000 字符）的请求体**
- [ ] 8.4 若阿里后续修复 flash，可按附录 A 的「仅换模型名」路径切回（维度不变，只需全量重嵌入）

## 9. DashScope 重排适配（执行会话「后端」完成于 2026-09-07，代码准备，独立于 1–6）

线上要把重排从硅基流动换成阿里百炼 `qwen3.7-text-rerank`，而两家接口方言不同：
百炼的 URL 是含 WorkspaceId 的完整端点、请求体嵌套 `input`/`parameters`、结果在
`output.results`。这一组只做代码侧适配，不动服务器配置——切换动作归第 3/4 组。

- [x] 7.1 `config.py` 新增 `rerank_provider`（`cohere` | `dashscope`），默认 `cohere`——不配置时行为与切换前逐字节一致
- [x] 7.2 `reranker.py` 抽出 `build_request()` 与 `unwrap_results()` 两个分派点，cohere 分支一行未改；dashscope 下 base_url 原样用作完整端点、请求体嵌套、结果自 `output` 取出
- [x] 7.3 失败哲学与共用预处理不变：截断、空文档占位、超时/异常/坏响应降级为 None 对两种方言一致
- [x] 7.4 `tests/test_reranker.py` 补 16 条 dashscope 用例（URL 不被追加后缀、请求体嵌套形状、嵌套响应解析、`output` 六种缺失形态降级、共用截断与占位仍生效、未知 provider 退回 cohere）；现有 39 条 cohere 用例全部保留且未改动
- [x] 7.5 `.env.example` 重排段加 `RERANK_PROVIDER` 说明与百炼示例（WorkspaceId 用占位符）；顺带修掉「调用超时(5s)」——`rerank_timeout_seconds` 实际默认 15
- [x] 7.6 `uv run pytest -m "not integration"` 全绿：724 passed / 2 skipped，覆盖率 79.29%（门槛 78%）

> 未知 provider 值退回 cohere 而非报错：重排是可降级链路，配置写错不该让问答链路启动失败。
> 代价是拼写错误不会被立刻发现——由 7.4 的用例把这个取舍钉住。
