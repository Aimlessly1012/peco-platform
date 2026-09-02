# 检索质量基线（M17）

评测分两档，跑的是同一份 golden 集（`services/rag/tests/eval/golden_set.json`，23 条，
local 11 / global 6 / impact 6），语料是 `services/rag/tests/fixtures/mini_repo`。

| 档 | 向量 | rerank | 跑法 | 判定 |
|---|---|---|---|---|
| 离线确定性档 | fake（md5 词袋） | 关闭 | CI 自动 | node_id 序列 vs 快照，不一致即红 |
| 真实模型档 | 真 embedding | 可选 | 手动 | 记录 hit@k / recall@k / MRR 数值 |

## 离线档：它测的不是召回质量

`conftest.fake_embed` 是 md5 词袋向量，**没有语义能力**。实测：查询「创建订单的接口」，
top1 是 `users.py:list_users`，而 `create_order` 根本没进前 8。

所以离线档不断言 golden 的 recall，只断言**返回的 node_id 序列与基线快照一致**——
它回答的是「检索行为有没有漂移」，不是「检索得准不准」。召回质量归真实档。

同理，快照**不含分数**：`RetrievedItem.score` 在管线里被覆写三次（cosine → RRF → rerank），
钉分数等于钉实现细节（design D2）。

### 记录顺序做了稳定化

RRF 会产出大量完全相同的融合分（三路各自 rank 组合出同值很常见）。实测一条 global
query 的 top-8，第 5～8 位是两两精确并列的 `0.016393442623` 与 `0.016129032258`，
这时先后完全取决于上游 Neo4j 向量查询在并列时的返回顺序，而那个顺序不保证稳定。

所以 harness 在记录前按 `(分数降序, node_id 升序)` 定序（`harness.stabilize`）。
被消掉的只有「分数相同、上游顺序抖动」这类假信号；分数真变了顺序照样变，守卫依然有效
（验证方式：手改快照里任意两项的位置，用例必红并列出前后序列）。

### 库里不能有任何其他项目（不只是同构的）

这一档真正的脆弱点在这里，比并列抖动严重得多：**快照以干净库为唯一权威口径**。
M17 上线时踩过实弹——快照在本机脏库（有一个真实项目）生成，本机连跑全绿，CI 干净库上
global/impact 两档必红。真实项目的真嵌入向量同样挤占全局召回窗口，不需要「同构」。

夹具因此带守卫（`_foreign_projects`）：库里存在非 `eval-*` 项目时，比对模式自动 skip
（本机脏库的红灯是假信号），重建模式直接 fail（脏库重建出的基线就是污染源）。CI 的库
天然干净，永远真跑——本地跑不跑得上不影响门禁。

`Neo4jVector` 生成的 Cypher 长这样（见 `vector_store.py` 模块注释第 1 条）：

```cypher
CALL db.index.vector.queryNodes($idx, $top_k * $ratio, $vec)   -- 召回窗口是全局的
WITH node, score LIMIT $top_k                                  -- 截断排在前面
<retrieval_query 里的 project 过滤>                             -- 过滤排在后面
```

而 fixture 仓在每个项目里的 fake 向量**完全相同**（`fake_embed` 只看文本，不看 project）。
库里每多一份同构的评测图，就有一批分数完全并列的节点跟本项目抢这个全局窗口的名额，各路
实际召回到的条数随之变化，RRF 分数跟着变——注意是分数真的变了，不是并列换位，`stabilize`
挡不住。

实测：库干净时连跑 6 次全绿；人为留下 2 份同构残留后连跑 3 次全红，漂移出现在前 4 条
**不并列**的结果上（`0.031280547410` 这类值本身变了）。

正常 teardown 会删掉自己建的图，但进程被杀、断言中途抛错都会留下残留。所以
`indexed_project` 建图前会先清掉库中所有 `eval-*` 项目（`_purge_eval_residue`），
只清这个自己的命名空间，真实项目与其他测试的 `test-*` 项目一概不碰。

如果快照仍在漂，先按用例失败信息里给的 Cypher 查一下有没有别的项目也带着这套 fixture 文件。

### 跑法

```bash
cd services/rag
uv run pytest tests/test_retrieval_eval.py -m eval --no-cov -q      # 比对基线（库不干净会 skip）
```

重建基线必须用干净库（一次性容器，用完即删）：

```bash
docker run -d --name m17-eval-neo4j -p 7999:7687 -e NEO4J_AUTH=neo4j/ragcoder123 -e 'NEO4J_PLUGINS=["apoc"]' neo4j:5.26-community
cd backend && NEO4J_URI=bolt://localhost:7999 EVAL_UPDATE_SNAPSHOT=1 uv run pytest tests/test_retrieval_eval.py -m eval --no-cov -q
docker rm -f m17-eval-neo4j
```

空 Neo4j 上 fixture 会自动建图，无手工准备步骤。重建后的快照 diff 要随 PR 评审。

快照按 question_type 分文件：`services/rag/tests/eval/snapshots/{local,global,impact}.json`。

## 真实模型档：质量基线

> **状态：首个基线已建立（2026-09-02）。** 后续每次跑完在下表追加一行；配置指纹与上一行
> 不同（换嵌入模型 / 维度 / rerank 开关 / top_k）就另起一行并注明「不可比」，不要覆盖旧行。

```bash
cd services/rag
uv run python scripts/eval_retrieval.py --out docs/retrieval-baseline-run.md
```

⚠️ `--out` 是整文件覆盖写入，**绝不要指向本文档**；出到 `retrieval-baseline-run.md` 再把数值手工填进下表。
脚本读的是仓库根 `.env`（真实 key），`EMBEDDING_BASE_URL` 只到 `/v1`，不要带 `/embeddings` 后缀（客户端自己拼，带了会 404）。

| 日期 | embedding 模型 | rerank | top_k | hit@k | recall@k | MRR | 备注 |
|---|---|---|---|---|---|---|---|
| 2026-09-02 | Qwen/Qwen3-VL-Embedding-8B（1024 维，SiliconFlow） | Qwen/Qwen3-Reranker-8B 开启，候选 ×3 | 8 | 1.0000 | 0.9022 | 0.8783 | **首个基线**，模板摘要。分组 recall/MRR：local 0.9545/0.8515、global 0.7639/0.8889、impact 0.9444/0.9167 |

配置指纹（脚本报告头部会打印，形如）：

```
embedding_dim=1024 embedding_model=Qwen/Qwen3-VL-Embedding-8B rerank_candidate_multiplier=3
rerank_enabled=True rerank_model=Qwen/Qwen3-Reranker-8B retrieval_top_k=8 eval_top_k=8
```
（以上即首个基线的指纹。）

指纹里任一项变化都会让数值不可比——对比历史基线前先核对指纹。

### 摘要来源的影响

脚本默认用**模板摘要**（不调 LLM）：file/module 摘要层的文本是结构化模板，
但仍走真 embedding 向量化，摘要层照常参与检索。评测的是检索链，不是摘要质量。
想看「LLM 摘要对召回的贡献」时加 `--real-summary`，成本显著上升。

## 评测集维护

`golden_set.json` 期望命中标到**文件粒度**（`expect_files`）而非 node_id：
node_id 含起始行号，改几行代码标注就失效，而文件粒度足以判定「有没有找对地方」。
`module_summary` 没有 file_path，用 `expect_modules` 匹配其 symbol。
`expect_symbols` 只是人工备注，不参与指标计算。

改评测集就是改这一个 JSON 文件，diff 可读，走代码评审。

## 附：真实模型档首跑完整报告（2026-09-02）

### 首跑完整报告 · 2026-09-02 10:47

config: embedding_dim=1024 embedding_model=Qwen/Qwen3-VL-Embedding-8B rerank_candidate_multiplier=3 rerank_enabled=True rerank_model=Qwen/Qwen3-Reranker-8B retrieval_top_k=8 eval_top_k=8
queries: 23

## 明细

| id         | type    | hit | recall | mrr  | 首个命中位次 | 命中目标 |
|---|---|---|---|---|---|---|
| local-01   | local   | ✓ | 1.00 | 1.00 | 1 | file:backend/routers/orders.py |
| local-02   | local   | ✓ | 1.00 | 1.00 | 1 | file:backend/routers/orders.py |
| local-03   | local   | ✓ | 0.50 | 1.00 | 1 | file:backend/routers/orders.py |
| local-04   | local   | ✓ | 1.00 | 0.17 | 6 | file:backend/services/order_service.py |
| local-05   | local   | ✓ | 1.00 | 1.00 | 1 | file:backend/models.py |
| local-06   | local   | ✓ | 1.00 | 1.00 | 1 | file:backend/routers/users.py |
| local-07   | local   | ✓ | 1.00 | 1.00 | 1 | file:backend/main.py |
| local-08   | local   | ✓ | 1.00 | 1.00 | 1 | file:frontend/lib/api.ts |
| local-09   | local   | ✓ | 1.00 | 1.00 | 1 | file:frontend/pages/orders.tsx |
| local-10   | local   | ✓ | 1.00 | 1.00 | 1 | file:frontend/components/OrderCard.tsx |
| local-11   | local   | ✓ | 1.00 | 0.20 | 5 | file:backend/main.py |
| global-01  | global  | ✓ | 0.50 | 0.33 | 3 | module:orders, module:users |
| global-02  | global  | ✓ | 1.00 | 1.00 | 1 | module:orders, file:backend/services/order_service.py, file:backend/routers/orders.py |
| global-03  | global  | ✓ | 1.00 | 1.00 | 1 | module:users, file:backend/routers/users.py |
| global-04  | global  | ✓ | 0.67 | 1.00 | 1 | file:frontend/lib/api.ts, file:backend/main.py |
| global-05  | global  | ✓ | 0.75 | 1.00 | 1 | file:frontend/pages/orders.tsx, file:backend/routers/orders.py, file:backend/services/order_service.py |
| global-06  | global  | ✓ | 0.67 | 1.00 | 1 | file:backend/routers/orders.py, file:backend/main.py, module:users, module:orders |
| impact-01  | impact  | ✓ | 0.67 | 1.00 | 1 | file:backend/routers/orders.py, file:backend/main.py |
| impact-02  | impact  | ✓ | 1.00 | 1.00 | 1 | file:backend/routers/orders.py, file:frontend/pages/orders.tsx |
| impact-03  | impact  | ✓ | 1.00 | 0.50 | 2 | file:backend/routers/orders.py, file:backend/services/order_service.py |
| impact-04  | impact  | ✓ | 1.00 | 1.00 | 1 | file:frontend/pages/index.tsx, file:frontend/pages/orders.tsx, file:frontend/lib/api.ts |
| impact-05  | impact  | ✓ | 1.00 | 1.00 | 1 | file:backend/models.py, file:backend/services/order_service.py, file:backend/routers/orders.py |
| impact-06  | impact  | ✓ | 1.00 | 1.00 | 1 | file:frontend/pages/orders.tsx, file:frontend/components/OrderCard.tsx |

## 汇总

| 分组 | 条数 | hit@k | recall@k | MRR |
|---|---|---|---|---|
| overall | 23 | 1.0000 | 0.9022 | 0.8783 |
| local | 11 | 1.0000 | 0.9545 | 0.8515 |
| global | 6 | 1.0000 | 0.7639 | 0.8889 |
| impact | 6 | 1.0000 | 0.9444 | 0.9167 |

摘要来源: 模板（未调用 LLM）
语料: backend/tests/fixtures/mini_repo
