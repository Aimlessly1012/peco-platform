"""检索链 LangChain 化的回归契约（M15 3.1）。

分两段：
- 上半部分不需要 Neo4j：组件形状、插槽 Cypher 的三个"坑"、citations 字段级断言
- 行为对齐由字段级断言钉住（新旧同题对照已在验收期完成使命后随旧实现删除）
  的同题对照，逐条比 node_id、顺序与 citation 字典。这是「行为零变化」这条红线的
  活证据，也是 tasks 3.2 线上对照的本地版。

"""
import uuid

import pytest

from app.core.config import settings
from app.services.retrieval import vector_store
from app.services.retrieval.components import (
    RRF_K,
    ReciprocalRankFuser,
    RerankCompressor,
)
from app.services.retrieval.models import (
    RetrievedItem,
    chunk_item,
    file_item,
    module_item,
)
from app.services.retrieval.vector_store import (
    CHUNK_INDEX,
    FETCH_MULTIPLIER,
    FILE_INDEX,
    MODULE_INDEX,
    RETRIEVAL_QUERIES,
)

# ---------------- citations 字段级契约 ----------------

CITATION_KEYS = {
    "file_path", "start_line", "end_line", "node_id", "symbol", "kind", "via_edge",
}


def test_citation_has_exactly_the_seven_contract_keys():
    """前端按这七个键渲染右栏引用。多一个少一个都是契约变更。"""
    item = chunk_item(
        {"name": "n1", "file_path": "src/a.py", "symbol": "fn", "symbol_type": "function",
         "start_line": 3, "end_line": 9, "code": "def fn(): ..."}, 0.9,
    )

    assert set(item.citation()) == CITATION_KEYS


def test_chunk_citation_field_values():
    item = chunk_item(
        {"name": "p:src/a.py:fn:3", "file_path": "src/a.py", "symbol": "fn",
         "symbol_type": "function", "start_line": 3, "end_line": 9, "code": "code"}, 0.9,
    )

    assert item.citation() == {
        "file_path": "src/a.py", "start_line": 3, "end_line": 9,
        "node_id": "p:src/a.py:fn:3", "symbol": "fn", "kind": "chunk",
        "via_edge": None,           # 直接命中必须是 None，不是空串
    }


def test_file_citation_field_values():
    item = file_item({"name": "p:src/a.py", "path": "src/a.py", "summary": "摘要"},
                     0.8, via="imports")

    assert item.citation() == {
        "file_path": "src/a.py", "start_line": 0, "end_line": 0,
        "node_id": "p:src/a.py", "symbol": "(file)", "kind": "file_summary",
        "via_edge": "imports",
    }


def test_module_citation_falls_back_to_bracket_label():
    """模块没有文件路径，前端靠 "[模块] xxx" 这个约定展示。"""
    item = module_item({"name": "p:module:orders", "module_name": "orders",
                        "summary": "订单模块"}, 0.7)

    citation = item.citation()
    assert citation["file_path"] == "[模块] orders"
    assert citation["kind"] == "module_summary"
    assert citation["symbol"] == "orders"


def test_module_symbol_derives_from_node_id_when_name_missing():
    """老数据没有 module_name 属性时从 node_id 尾段还原（M2 起的兼容行为）。"""
    item = module_item({"name": "p:module:orders", "summary": "s"}, 0.7)

    assert item.symbol == "orders"


@pytest.mark.parametrize("builder", [chunk_item, file_item])
def test_missing_props_fall_back_to_contract_defaults(builder):
    """Neo4jVector 会把 metadata 里值为 null 的键整个丢掉——构造器必须照样给出
    契约要求的默认值（行号 0、字符串空串），不能 KeyError 也不能出 None。"""
    item = builder({}, 0.1)

    citation = item.citation()
    assert isinstance(citation["start_line"], int)
    assert isinstance(citation["end_line"], int)
    assert citation["via_edge"] is None


# ---------------- retrieval_query 插槽（D2）----------------


@pytest.mark.parametrize("index", [CHUNK_INDEX, FILE_INDEX, MODULE_INDEX])
def test_every_route_filters_by_project_in_the_slot(index):
    """跨项目隔离靠这一句。丢了它就会串项目返回代码。"""
    assert "node.project_id = $pid" in RETRIEVAL_QUERIES[index]


@pytest.mark.parametrize("index", [FILE_INDEX, MODULE_INDEX])
def test_summary_routes_coalesce_text(index):
    """text 为 null 时库会让**整次检索**抛 ValueError（不是跳过那一条）。
    摘要可能为空，必须 coalesce。"""
    assert "coalesce(node.summary, '')" in RETRIEVAL_QUERIES[index]


def test_chunk_route_coalesces_code():
    assert "coalesce(node.code, '')" in RETRIEVAL_QUERIES[CHUNK_INDEX]


@pytest.mark.parametrize(
    "index,keys",
    [
        (CHUNK_INDEX, ["name", "file_path", "symbol", "symbol_type",
                       "start_line", "end_line"]),
        (FILE_INDEX, ["name", "path"]),
        (MODULE_INDEX, ["name", "module_name"]),
    ],
)
def test_slot_metadata_covers_every_citation_source_field(index, keys):
    for key in keys:
        assert f"{key}: node." in RETRIEVAL_QUERIES[index]


async def test_vector_route_overfetches_then_slices(monkeypatch):
    """库生成的 Cypher 把 LIMIT 排在我们的 project 过滤之前，所以必须按
    k×FETCH_MULTIPLIER 取回、客户端再切 k——直接按 k 要会拿不满。"""
    seen = {}

    class FakeStore:
        def similarity_search_with_score_by_vector(self, **kwargs):
            seen.update(kwargs)
            from langchain_core.documents import Document
            return [
                (Document(page_content=f"code {i}",
                          metadata={"name": f"n{i}", "file_path": f"f{i}.py"}), 0.9)
                for i in range(kwargs["k"])
            ]

    monkeypatch.setattr(vector_store, "get_store", lambda _i: FakeStore())

    items = await vector_store.vector_route(CHUNK_INDEX, [0.1], "pid-1", 5, "问题")

    assert seen["k"] == 5 * FETCH_MULTIPLIER      # 向库多要
    assert seen["params"] == {"pid": "pid-1"}
    assert seen["query"] == "问题"                 # 纯向量检索也被强制要求传
    assert len(items) == 5                         # 客户端切回 k


async def test_vector_route_maps_document_back_to_item(monkeypatch):
    """Document(page_content, metadata) → RetrievedItem 的字段还原。"""
    from langchain_core.documents import Document

    class FakeStore:
        def similarity_search_with_score_by_vector(self, **kwargs):
            return [(
                Document(page_content="def fn(): ...",
                         metadata={"name": "p:src/a.py:fn:3", "file_path": "src/a.py",
                                   "symbol": "fn", "symbol_type": "function",
                                   "start_line": 3, "end_line": 9}),
                0.77,
            )]

    monkeypatch.setattr(vector_store, "get_store", lambda _i: FakeStore())

    (item,) = await vector_store.vector_route(CHUNK_INDEX, [0.1], "p", 1)

    assert item.content == "def fn(): ..."     # 正文从 page_content 回填
    assert item.score == 0.77
    assert item.citation()["node_id"] == "p:src/a.py:fn:3"
    assert item.citation()["start_line"] == 3


async def test_vector_route_short_circuits_on_zero_k(monkeypatch):
    """k=0 不该发查询（global 路 k//2 在 top_k=1 时会是 0）。"""
    def boom(_i):
        raise AssertionError("k=0 时不该建 store")

    monkeypatch.setattr(vector_store, "get_store", boom)

    assert await vector_store.vector_route(CHUNK_INDEX, [0.1], "p", 0) == []


# ---------------- Embeddings 组件（D3）----------------


def test_retrieval_embeddings_disables_token_chunking(monkeypatch):
    """check_embedding_ctx_length 默认为 True 时 LangChain 会按 token 切块、
    分别嵌入再加权平均——那等于悄悄换了向量空间，和索引侧对不上。"""
    vector_store.reset_stores()
    monkeypatch.setattr(settings, "embedding_api_key", "k")

    emb = vector_store.retrieval_embeddings()

    assert emb.check_embedding_ctx_length is False
    assert emb.dimensions == settings.embedding_dim
    assert emb.model == settings.embedding_model
    vector_store.reset_stores()


def test_retrieval_embeddings_is_cached(monkeypatch):
    vector_store.reset_stores()
    monkeypatch.setattr(settings, "embedding_api_key", "k")

    assert vector_store.retrieval_embeddings() is vector_store.retrieval_embeddings()
    vector_store.reset_stores()


async def test_embed_query_truncates_like_index_side(monkeypatch):
    """同一模型的输入上限是同一个，检索侧不能漏掉截断护栏。"""
    vector_store.reset_stores()
    monkeypatch.setattr(settings, "embedding_max_chars", 10)
    seen = {}

    class FakeEmb:
        async def aembed_query(self, text):
            seen["text"] = text
            return [0.1]

    monkeypatch.setattr(vector_store, "retrieval_embeddings", lambda: FakeEmb())

    await vector_store.embed_query("x" * 50)

    assert seen["text"] == "x" * 10
    vector_store.reset_stores()


# ---------------- 自持组件：RRF 与 rerank（D1/D4）----------------


def make_items(count: int) -> list[RetrievedItem]:
    return [
        chunk_item({"name": f"n{i}", "file_path": f"src/f{i}.py", "symbol": f"fn{i}",
                    "symbol_type": "function", "start_line": 1, "end_line": 9,
                    "code": f"code {i}"}, 1.0 / (i + 1))
        for i in range(count)
    ]
def test_rrf_k_constant_unchanged():
    assert RRF_K == 60
async def test_rerank_failure_keeps_input_order(monkeypatch):
    """精排挂掉只降级，不能让问答挂掉。"""
    from app.services.retrieval import reranker

    async def fail(*_a, **_k):
        return None

    monkeypatch.setattr(reranker, "rerank", fail)
    items = make_items(6)

    out = await RerankCompressor().compress("q", items, 3)

    assert [i.node_id for i in out] == ["n0", "n1", "n2"]


async def test_rerank_empty_input_is_noop():
    assert await RerankCompressor().compress("q", [], 3) == []


def test_no_langchain_classic_import_in_retrieval_layer():
    """D1：不引 langchain-classic 的 legacy 组件。它作为 langchain-neo4j 的
    传递依赖装在环境里，但我们的代码一行都不许 import 它。"""
    import pathlib

    layer = pathlib.Path(__file__).parent.parent / "app" / "services" / "retrieval"
    for path in layer.glob("*.py"):
        assert "langchain_classic" not in path.read_text(), path.name