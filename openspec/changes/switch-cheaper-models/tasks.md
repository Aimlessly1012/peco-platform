## 1. 前置验证（无破坏，全部可中止）

- [ ] 1.1 **需用户先把百炼 key 放进 `~/.peco-dashscope.key`**（600 权限）；脚本读文件不回显，key 不再出现在任何命令与日志里。做完整套后建议在控制台换一把——它在聊天记录里待过
- [ ] 1.2 探针：用该 key 调 `/models`，确认 `qwen3.8-flash` / `qwen3.7-text-embedding-flash` 在列表里；各发一次最小请求记录 HTTP 状态与耗时
- [ ] 1.3 维度实测：`qwen3.7-text-embedding-flash` 带 `dimensions=1024` 与不带各请求一次，确认实际返回维度都是 1024——D2 的「延迟一步失效」就防在这里
- [ ] 1.4 限速探测：对 `qwen3.8-flash` 做并发 4、连发 20 次的压测，记录是否出现 429；触发则在控制台申请提额（D5）
- [ ] 1.5 记录调用前后的账户余额差，得到实际单价，与文档价比对
- [ ] 1.6 **需用户提供百炼 WorkspaceId**；用 `qwen3.7-text-rerank` 的原生端点发一次 2 文档请求，记录响应形状（应为 `output.results[].index/relevance_score`），供 D7 适配的测试夹具对照

## 2. 质量基线（换之前必须有对照）

- [ ] 2.1 **在服务器上**（本地嵌入配置与线上漂移：本地是 VL 版 1024 维、线上是 8B 版 4096 维，本地跑出的指标与线上没有可比性）以当前模型配置跑 `services/rag/scripts/eval_retrieval.py`，产出含配置指纹的指标报告
- [ ] 2.2 基线数值与配置指纹落盘到本 change 目录，作为 D4「90% 门槛」的比较基准
- [ ] 2.3 记一组真实查询的人工抽查结果（ColaMD 上 3–5 条），补足 golden set 基于 mini_repo 的规模局限

## 3. 摘要与问答模型切换（可回退，先做）

- [ ] 3.1 改服务器 `services/rag/.env`：`CHAT_BASE_URL` 与 `CHAT_API_KEY` 指向百炼，`SUMMARY_MODEL=qwen3.8-flash`、`CHAT_MODEL=qwen3.8-flash`、`GENERATE_MODEL` 留空；key 由脚本从本地文件读入后经 SSH 写入，不经命令行参数
- [ ] 3.2 `up -d --force-recreate --no-deps backend worker`（env 变更不走 build），确认容器内 `CHAT_BASE_URL` 与 key 哈希与预期一致
- [ ] 3.3 触发一次 ColaMD 重索引，确认 summarize 与 report 阶段走通；在 `/rag` 发一句聊天确认问答链路
- [ ] 3.4 对比摘要文本质量：新旧模型对同几个文件的摘要产出，判据是「不误导」而非「更精妙」
- [ ] 3.5 记录本次索引的调用次数与余额消耗，得到新的单位成本

## 4. 重排适配（代码，已派给执行会话）

- [ ] 4.1 `app/core/config.py` 新增 `rerank_provider`（`cohere` 默认 | `dashscope`）；`reranker.py` 按 D7 分支；`tests/test_reranker.py` 补 dashscope 用例；`.env.example` 加说明
- [ ] 4.2 审阅：cohere 路径零改动、全部既有测试原样、失败仍返回 None；`uv run pytest -m "not integration"` 全绿、覆盖率 ≥78%
- [ ] 4.3 合入 main，自动部署构建 backend/worker；先**不**开启（`RERANK_*` 仍留空），等 1.6 的 WorkspaceId 与响应形状确认后再配

## 5. 嵌入模型迁移（不可逆，严格按序，见 DEPLOY.md 附录 A）

- [ ] 5.1 迁移前 `pg_dump` 一份（切栈时没做这一步的教训）
- [ ] 5.2 停 worker——避免迁移中途有任务写入旧维度向量（D3）
- [ ] 5.3 DROP 三个 Neo4j 向量索引（`chunk_embedding` / `file_summary_embedding` / `module_summary_embedding`，以 `graph/client.py` 的 `VECTOR_INDEXES` 为准）
- [ ] 5.4 同时改 `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL=qwen3.7-text-embedding-flash` / `EMBEDDING_DIM=1024`——只改其一会被启动校验拦下，那是防护生效而非故障
- [ ] 5.5 起 backend，确认三个向量索引按 1024 维自动重建、启动无维度冲突报错
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
