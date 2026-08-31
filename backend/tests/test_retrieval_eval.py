"""离线确定性评测档（M17 3.4）。

fake 向量（conftest 的 md5 词袋）+ rerank 关闭，对 golden 集逐条跑 `search_layered`，
断言返回的 node_id 序列与已提交的基线快照一致。

**只钉序列，不钉分数**：RetrievedItem.score 在管线里被覆写三次（cosine → RRF → rerank），
钉分数等于钉实现细节，改一次融合权重就全红（design D2）。

**为什么不在这里断言 golden 的 recall**：fake 向量没有语义能力（查「创建订单的接口」，
top1 是 list_users），指标数值毫无意义。召回质量由真实模型档负责
（scripts/eval_retrieval.py），这一档只回答「检索行为有没有漂移」。

**这一档对「库里有没有同构的其他项目」敏感**，建图前必须清干净自己的命名空间。
原因在 vector_store.py 模块注释第 1 条：库生成的 Cypher 是

    CALL db.index.vector.queryNodes($idx, $top_k * $ratio, $vec)   ← 召回窗口是全局的
    WITH node, score LIMIT $top_k                                  ← 截断排在前面
    <retrieval_query 里的 project 过滤>                             ← 过滤排在后面

而窗口是全局的意味着：**库里任何其他项目的节点都在跟本项目抢名额**——同构的评测残留
（分数完全并列）会，真实项目的真嵌入向量也会。各路实际召回到的条数随之变化，RRF 排名
跟着变——表现就是快照序列莫名漂移。实测两例：①库干净时连跑 6 次全绿，人为留下 2 份
同构残留后连跑 3 次全红；②M17 上线时快照在本机脏库（有一个真实项目）生成，本机连跑
全绿、CI 干净库上 global/impact 两档漂移必红。

因此本档的口径是：**快照以干净库为唯一权威**。indexed_project 建图前先清掉 `eval-*`
残留（_purge_eval_residue，自己的命名空间）；若库里还存在任何非 eval-* 项目（真实项目
或其他测试残留，_foreign_projects），比对模式自动 skip（本机脏库跑出的红灯是假信号），
重建模式直接 fail（脏库重建出的基线就是污染源）。CI 的库天然干净，永远真跑。

重建基线快照（必须干净库；改动检索链后确认变化符合预期，再提交 diff 供评审）：

    docker run -d --name m17-eval-neo4j -p 7999:7687 -e NEO4J_AUTH=neo4j/ragcoder123 \
        -e 'NEO4J_PLUGINS=["apoc"]' neo4j:5.26-community   # 建图用到 apoc.create.addLabels
    cd backend && NEO4J_URI=bolt://localhost:7999 EVAL_UPDATE_SNAPSHOT=1 \
        uv run pytest tests/test_retrieval_eval.py -m eval --no-cov -q
    docker rm -f m17-eval-neo4j
"""
import json
import os
import uuid

import pytest

from app.core.config import settings
from app.graph.client import (
    close_driver,
    delete_project_graph,
    ensure_vector_index,
    get_driver,
)
from tests.eval.harness import (
    QUESTION_TYPES,
    config_fingerprint,
    load_golden,
    run_eval,
    snapshot_path,
    snapshot_payload,
)
from tests.helpers.fixture_graph import index_fixture_repo

# integration：要 Neo4j。eval：便于 `-m eval` 单独跑这一档
# （eval marker 尚未注册进 pyproject，见交付说明——那个文件归后端会话独占）
pytestmark = [pytest.mark.integration, pytest.mark.eval]

EVAL_TOP_K = 8
UPDATE = os.getenv("EVAL_UPDATE_SNAPSHOT") == "1"


async def _purge_eval_residue() -> list[str]:
    """清掉库中所有 `eval-*` 项目，保证评测总从同一起点开跑。

    正常 teardown 会删掉自己建的图，但进程被杀、断言中途抛错等情况会留下残留，
    而残留会让后续每一次跑都漂（原因见模块 docstring）。只清 `eval-` 前缀这个
    自己的命名空间：真实项目与其他测试的 `test-*` 项目一概不碰。
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n) WHERE n.project_id STARTS WITH 'eval-' "
            "RETURN DISTINCT n.project_id AS pid"
        )
        pids = [record["pid"] async for record in result]
    for pid in pids:
        await delete_project_graph(pid)
    return sorted(pids)


async def _foreign_projects() -> list[str]:
    """库中所有非 `eval-*` 的项目（真实项目或其他测试残留）。

    向量召回窗口是全局的（见模块 docstring），任何外来节点都会挤占名额，让序列
    与干净库（CI）不可比。外来项目不是我们的数据，不能删，只能拒跑。
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n) WHERE n.project_id IS NOT NULL "
            "AND NOT n.project_id STARTS WITH 'eval-' "
            "RETURN DISTINCT n.project_id AS pid LIMIT 10"
        )
        return sorted([record["pid"] async for record in result])


@pytest.fixture(scope="module")
def offline_config():
    """离线档固定检索配置：rerank 关闭 + top_k 固定，保证快照可比。

    rerank 是外部 API，离线本来就不可用；显式关掉是为了让「配置指纹」这件事有意义，
    而不是依赖环境恰好没配 key。
    """
    # rerank_enabled 是 base_url/api_key/model 三项派生出来的只读 property，
    # 要关它得把这三项置空（reranker.is_enabled 读的就是这个 property）
    saved = {
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_base_url": settings.rerank_base_url,
        "rerank_api_key": settings.rerank_api_key,
        "rerank_model": settings.rerank_model,
    }
    settings.retrieval_top_k = EVAL_TOP_K
    settings.rerank_base_url = ""
    settings.rerank_api_key = ""
    settings.rerank_model = ""
    assert not settings.rerank_enabled, "离线档必须在 rerank 关闭下跑"
    yield
    for key, value in saved.items():
        setattr(settings, key, value)


@pytest.fixture(scope="module")
async def indexed_project(offline_config):
    """空 Neo4j 上自动建图——评测无任何手工准备步骤（spec: 评测集可复现建图）。"""
    # module 级 fixture 拿不到 function 级的 fake_embedder，这里自己打桩
    from unittest.mock import patch

    from tests.conftest import fake_embed

    class FakeEmbeddings:
        def embed_query(self, text):
            return fake_embed(text)

        def embed_documents(self, texts):
            return [fake_embed(t) for t in texts]

        async def aembed_query(self, text):
            return fake_embed(text)

        async def aembed_documents(self, texts):
            return [fake_embed(t) for t in texts]

    class FakeEmbedder:
        async def embed_texts(self, texts, on_progress=None):
            return [fake_embed(t) for t in texts]

        async def embed_query(self, text):
            return fake_embed(text)

    class FakeSummarizer:
        async def summarize_file(self, path, imports, chunks, content):
            return f"{path} 的摘要：{' '.join(c.symbol for c in chunks)}"

        async def summarize_module(self, name, kind, prefix, entries, extra):
            return f"模块 {name}（{kind}）负责 {prefix or name}，入口 {', '.join(entries)}"

        async def summarize_project(self, readme, module_map, module_summaries):
            return "mini-shop：订单与用户的前后端最小示例"

    from app.services.ingest import embedder as embedder_module
    from app.services.retrieval import vector_store

    await ensure_vector_index()
    residue = await _purge_eval_residue()
    if residue:
        print(f"\n[eval] 清掉库中残留的评测项目（会导致序列漂移）：{residue}")
    foreign = await _foreign_projects()
    if foreign:
        await close_driver()
        if UPDATE:
            pytest.fail(
                f"重建基线必须在干净 Neo4j 上进行（快照以干净库为权威口径），"
                f"当前库里有其他项目：{foreign}。用一次性容器重建，见模块 docstring。"
            )
        pytest.skip(
            f"库不干净（存在非 eval-* 项目：{foreign}），离线快照与干净库不可比，"
            f"跳过以免假红灯。此档以 CI 的干净库为权威；本机想跑见模块 docstring 的一次性容器。"
        )
    pid = f"eval-{uuid.uuid4().hex[:8]}"
    with (
        patch.object(type(embedder_module.embedder), "embed_texts", FakeEmbedder.embed_texts),
        patch.object(type(embedder_module.embedder), "embed_query", FakeEmbedder.embed_query),
        patch.object(vector_store, "retrieval_embeddings", lambda: FakeEmbeddings()),
    ):
        vector_store.reset_stores()  # 模块级缓存：换嵌入实现后必须重置（vector_store.py）
        await index_fixture_repo(pid, FakeEmbedder(), FakeSummarizer())
        yield pid
    vector_store.reset_stores()
    await delete_project_graph(pid)
    await close_driver()


@pytest.fixture(scope="module")
async def eval_results(indexed_project):
    """跑一次评测，三个 question_type 的用例共用（避免重复建图与检索）。"""
    return await run_eval(
        indexed_project, top_k=EVAL_TOP_K, strip_prefix=indexed_project
    )


@pytest.mark.parametrize("question_type", QUESTION_TYPES)
async def test_offline_snapshot(eval_results, question_type):
    """node_id 序列与基线快照逐条比对；不一致时列出漂移的 query 与前后序列。"""
    subset = [r for r in eval_results if r.query.question_type == question_type]
    assert subset, f"golden 集里没有 {question_type} 类问题"

    payload = snapshot_payload(subset, EVAL_TOP_K)
    path = snapshot_path(question_type)

    if UPDATE or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not UPDATE:
            pytest.fail(
                f"{path.name} 之前不存在，已生成初始快照——请检查内容后提交，然后重跑"
            )
        return

    baseline = json.loads(path.read_text(encoding="utf-8"))

    assert baseline["config"] == payload["config"], (
        "检索配置变了，快照不可比。确认变化符合预期后用 "
        "EVAL_UPDATE_SNAPSHOT=1 重建快照\n"
        f"  基线: {baseline['config']}\n  当前: {payload['config']}"
    )

    drifted = [
        (qid, baseline["queries"].get(qid), ids)
        for qid, ids in payload["queries"].items()
        if baseline["queries"].get(qid) != ids
    ]
    missing = sorted(set(baseline["queries"]) - set(payload["queries"]))

    if drifted or missing:
        report = ["检索行为发生漂移："]
        for qid, before, after in drifted:
            report.append(f"\n[{qid}]")
            report.append(f"  基线: {before}")
            report.append(f"  当前: {after}")
        if missing:
            report.append(f"\n快照里有但本次没跑到的 query: {missing}")
        report.append(
            "\n先排除环境因素：库里任何其他项目的节点都会挤占全局召回窗口（见模块"
            " docstring），序列会漂但不是代码问题。本档已自动清理 eval-* 残留并在"
            "存在外来项目时 skip——如果你看到这条失败，说明库在建图后中途被写入了"
            "新项目，或检索行为真的变了。诊断残留：\n"
            "  MATCH (n) WHERE n.project_id IS NOT NULL RETURN DISTINCT n.project_id"
        )
        report.append(
            "\n若变化符合预期：cd backend && EVAL_UPDATE_SNAPSHOT=1 "
            "uv run pytest tests/test_retrieval_eval.py -m eval --no-cov"
        )
        pytest.fail("\n".join(report))


async def test_snapshot_pins_node_ids_not_scores(eval_results):
    """spec: 分数尺度变化不误报——快照内容里不能出现任何分数字段。"""
    payload = snapshot_payload(eval_results, EVAL_TOP_K)
    text = json.dumps(payload)
    assert "score" not in text, "快照不得包含分数（score 在管线中被覆写三次）"
    for ids in payload["queries"].values():
        assert all(isinstance(i, str) for i in ids)


async def test_golden_set_shape():
    """spec: golden 集 ≥20 条且三类覆盖。"""
    queries = load_golden()
    assert len(queries) >= 20
    kinds = {q.question_type for q in queries}
    assert kinds == set(QUESTION_TYPES), f"三类未覆盖全: {kinds}"


async def test_fingerprint_is_stable():
    """spec: 相同配置两次运行指纹一致。"""
    assert config_fingerprint() == config_fingerprint()
