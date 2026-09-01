"""Rerank 客户端与检索接入单测（M7 B2/B3）。

关键兼容约束：三项配置任一为空 = 完全关闭，一个请求都不该发出，
现有全部行为与测试不受影响——所以"关闭态不发请求"是本文件的头号断言。
"""
import httpx
import pytest

from app.core.config import settings
from app.services.retrieval import reranker
from app.services.retrieval.reranker import is_enabled, parse_ranking, rerank


@pytest.fixture
def rerank_on(monkeypatch):
    monkeypatch.setattr(settings, "rerank_base_url", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(settings, "rerank_api_key", "test-key")
    monkeypatch.setattr(settings, "rerank_model", "Qwen/Qwen3-Reranker-8B")


@pytest.fixture
def rerank_off(monkeypatch):
    monkeypatch.setattr(settings, "rerank_base_url", "")
    monkeypatch.setattr(settings, "rerank_api_key", "")
    monkeypatch.setattr(settings, "rerank_model", "")


def mock_transport(monkeypatch, handler):
    """把 AsyncClient 换成走 MockTransport 的版本，并记录请求。"""
    seen: list[httpx.Request] = []
    original = httpx.AsyncClient   # 先存原始类，否则 factory 内部会查到自己 → 递归

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return original(transport=httpx.MockTransport(wrapped), **kwargs)

    monkeypatch.setattr(reranker.httpx, "AsyncClient", factory)
    return seen


# ---------------- 开关语义 ----------------


def test_disabled_by_default(rerank_off):
    assert is_enabled() is False


@pytest.mark.parametrize("missing", ["rerank_base_url", "rerank_api_key", "rerank_model"])
def test_any_empty_field_disables(rerank_on, monkeypatch, missing):
    """spec: 三项任一为空即关闭。"""
    monkeypatch.setattr(settings, missing, "")
    assert is_enabled() is False


async def test_disabled_sends_no_request(rerank_off, monkeypatch):
    """spec 场景: 未配置时不发起任何 /rerank 请求。"""
    seen = mock_transport(monkeypatch, lambda r: httpx.Response(200, json={}))

    assert await rerank("查询", ["文档"]) is None
    assert seen == []


async def test_enabled_but_empty_input_sends_no_request(rerank_on, monkeypatch):
    seen = mock_transport(monkeypatch, lambda r: httpx.Response(200, json={}))

    assert await rerank("", ["文档"]) is None
    assert await rerank("查询", []) is None
    assert seen == []


# ---------------- 正常重排 ----------------


def ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"results": [
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.5},
            {"index": 1, "relevance_score": 0.1},
        ]},
    )


def ok_handler_n(request: httpx.Request) -> httpx.Response:
    """按实际文档数生成排名（候选池大小随 top_k 变化）。"""
    import json

    count = len(json.loads(request.content)["documents"])
    return httpx.Response(200, json={"results": [
        {"index": i, "relevance_score": float(count - i)} for i in range(count)
    ]})


async def test_rerank_returns_ranking_desc(rerank_on, monkeypatch):
    mock_transport(monkeypatch, ok_handler)

    ranking = await rerank("订单创建", ["甲", "乙", "丙"], top_n=3)

    assert ranking == [(2, 0.9), (0, 0.5), (1, 0.1)]


async def test_rerank_sorts_even_if_server_unordered(rerank_on, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"index": 0, "relevance_score": 0.2},
            {"index": 1, "relevance_score": 0.8},
        ]})

    mock_transport(monkeypatch, handler)
    assert await rerank("q", ["甲", "乙"]) == [(1, 0.8), (0, 0.2)]


async def test_request_shape_is_cohere_style(rerank_on, monkeypatch):
    """URL 由 base_url 拼 /rerank；body 为 Cohere 风格；带 Bearer 头。"""
    import json

    seen = mock_transport(monkeypatch, ok_handler)
    await rerank("订单创建", ["甲", "乙", "丙"], top_n=2)

    request = seen[0]
    assert str(request.url) == "https://api.siliconflow.cn/v1/rerank"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "Qwen/Qwen3-Reranker-8B"
    assert body["query"] == "订单创建"
    assert body["documents"] == ["甲", "乙", "丙"]
    assert body["top_n"] == 2


async def test_base_url_trailing_slash_tolerated(rerank_on, monkeypatch):
    monkeypatch.setattr(settings, "rerank_base_url", "https://api.siliconflow.cn/v1/")
    seen = mock_transport(monkeypatch, ok_handler)

    await rerank("q", ["甲", "乙", "丙"])

    assert str(seen[0].url) == "https://api.siliconflow.cn/v1/rerank"


async def test_documents_are_truncated(rerank_on, monkeypatch):
    """8B 重排模型上下文有限，单篇截前 1500 字符。"""
    import json

    seen = mock_transport(monkeypatch, ok_handler)
    await rerank("q", ["x" * 5000, "y", "z"])

    body = json.loads(seen[0].content)
    assert len(body["documents"][0]) == settings.rerank_max_chars


async def test_blank_document_becomes_placeholder(rerank_on, monkeypatch):
    """空文档会被部分服务端判非法，占位成空格。"""
    import json

    seen = mock_transport(monkeypatch, ok_handler)
    await rerank("q", ["", "  ", "正文"])

    body = json.loads(seen[0].content)
    assert body["documents"][0] == " "


async def test_top_n_never_exceeds_document_count(rerank_on, monkeypatch):
    import json

    seen = mock_transport(monkeypatch, ok_handler)
    await rerank("q", ["甲", "乙"], top_n=50)

    assert json.loads(seen[0].content)["top_n"] == 2


# ---------------- 降级路径 ----------------


async def test_timeout_degrades_to_none(rerank_on, monkeypatch):
    """spec 场景: 超时 → None（调用方保持 RRF 顺序），不抛异常。"""
    def handler(request):
        raise httpx.TimeoutException("timeout", request=request)

    mock_transport(monkeypatch, handler)
    assert await rerank("q", ["甲", "乙"]) is None


async def test_http_error_degrades_to_none(rerank_on, monkeypatch):
    mock_transport(monkeypatch, lambda r: httpx.Response(500, text="boom"))
    assert await rerank("q", ["甲", "乙"]) is None


async def test_connection_error_degrades_to_none(rerank_on, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    mock_transport(monkeypatch, handler)
    assert await rerank("q", ["甲", "乙"]) is None


async def test_non_json_body_degrades_to_none(rerank_on, monkeypatch):
    mock_transport(monkeypatch, lambda r: httpx.Response(200, text="not json"))
    assert await rerank("q", ["甲", "乙"]) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},                                                   # 没有 results
        {"results": []},                                      # 空 results
        {"results": "不是列表"},
        {"results": [{"relevance_score": 0.5}]},              # 缺 index
        {"results": [{"index": 0}]},                          # 缺分数
        {"results": [{"index": 99, "relevance_score": 0.5}]},  # 越界下标
        {"results": [{"index": -1, "relevance_score": 0.5}]},
        {"results": [{"index": "0", "relevance_score": 0.5}]},  # 类型不对
        {"results": ["不是对象"]},
    ],
)
async def test_bad_response_shapes_degrade_to_none(rerank_on, monkeypatch, payload):
    """越界下标尤其危险——照单收下会让调用方 IndexError。"""
    mock_transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    assert await rerank("q", ["甲", "乙"]) is None


def test_parse_ranking_accepts_score_alias():
    assert parse_ranking({"results": [{"index": 1, "score": 0.7}]}, 2) == [(1, 0.7)]


# ---------------- search_layered 接入（M7 B3） ----------------


def make_items(count: int):
    from app.services.retrieval.service import RetrievedItem

    return [
        RetrievedItem(
            kind="chunk", node_id=f"n{i}", file_path=f"src/f{i}.py", symbol=f"fn{i}",
            symbol_type="function", start_line=1, end_line=9,
            content=f"code {i}", score=1.0 / (i + 1),
        )
        for i in range(count)
    ]


@pytest.fixture
def search_stub(monkeypatch):
    """打桩向量检索与图扩展，只留 RRF → rerank → 返回这条链路。"""
    from app.services.retrieval import service

    state = {"pool_size": None, "expanded": []}

    async def fake_embed_query(text):
        return [0.1, 0.2]

    async def fake_vector_route(index_name, vec, project_id, k, query=""):
        # 每路返回足量候选（刻意不按 k 截断），实际条数由 RRF 的 top_k 决定
        from app.services.retrieval.models import chunk_item, file_item, module_item
        from app.services.retrieval.vector_store import (
            CHUNK_INDEX, FILE_INDEX, MODULE_INDEX,
        )

        build = {CHUNK_INDEX: chunk_item, FILE_INDEX: file_item,
                 MODULE_INDEX: module_item}[index_name]
        return [
            build({"name": f"n{i}", "file_path": f"src/f{i}.py", "symbol": f"fn{i}",
                   "symbol_type": "function", "start_line": 1, "end_line": 9,
                   "code": f"code {i}"}, 1.0 / (i + 1))
            for i in range(40)
        ]

    async def fake_expand(project_id, ids):
        return state["expanded"]

    # M15：接缝从 service._vector_query 移到 vector_store.vector_route（组件层），
    # 断言一字未动——测的是 RRF → rerank → 图扩展这条链路的行为
    monkeypatch.setattr(service, "embed_query", fake_embed_query)
    monkeypatch.setattr(service, "vector_route", fake_vector_route)
    monkeypatch.setattr(service, "expand_one_hop", fake_expand)
    return state


async def test_search_without_rerank_unchanged(rerank_off, search_stub, monkeypatch):
    """spec 场景: 关闭时行为与 M6 完全一致——不发请求，返回条数不变。"""
    from app.services.retrieval.service import search_layered

    seen = mock_transport(monkeypatch, ok_handler)
    results = await search_layered("p", "查询", "local", top_k=5)

    assert seen == []
    assert len(results) == 5
    assert [r.node_id for r in results] == ["n0", "n1", "n2", "n3", "n4"]


async def test_search_with_rerank_reorders(rerank_on, search_stub, monkeypatch):
    """spec 场景: 最终顺序为 relevance_score 降序。"""
    from app.services.retrieval.service import search_layered

    def handler(request):
        import json
        docs = json.loads(request.content)["documents"]
        # 倒序打分：下标越大越相关，于是候选池最后一条应该被排到第一
        return httpx.Response(200, json={"results": [
            {"index": i, "relevance_score": float(i + 1)} for i in range(len(docs))
        ]})

    seen = mock_transport(monkeypatch, handler)
    results = await search_layered("p", "查询", "local", top_k=5)

    assert len(seen) == 1
    assert len(results) == 5
    # 候选池是 5×3=15 条，重排后第一名应是原第 15 条
    assert results[0].node_id == "n14"
    assert [r.score for r in results] == sorted(
        [r.score for r in results], reverse=True
    )


async def test_rerank_candidate_pool_is_three_times_top_k(rerank_on, search_stub, monkeypatch):
    """候选池 = top_k × 3（关闭时不扩池，避免多余的图查询与内存）。"""
    import json

    from app.services.retrieval.service import search_layered

    seen = mock_transport(monkeypatch, ok_handler_n)
    await search_layered("p", "查询", "local", top_k=4)

    assert len(json.loads(seen[0].content)["documents"]) == 12


async def test_rerank_failure_keeps_rrf_order(rerank_on, search_stub, monkeypatch):
    """spec 场景: 超时/坏响应 → 按 RRF 顺序返回 top_k，问答正常完成。"""
    from app.services.retrieval.service import search_layered

    def handler(request):
        raise httpx.TimeoutException("timeout", request=request)

    mock_transport(monkeypatch, handler)
    results = await search_layered("p", "查询", "local", top_k=5)

    assert len(results) == 5
    assert [r.node_id for r in results] == ["n0", "n1", "n2", "n3", "n4"]


async def test_impact_mode_skips_rerank(rerank_on, search_stub, monkeypatch):
    """spec: 影响面模式不走 rerank（它按图距离排序）。"""
    from app.services.retrieval.service import search_layered

    seen = mock_transport(monkeypatch, ok_handler)
    results = await search_layered("p", "改它影响什么", "impact", top_k=5)

    assert seen == []
    assert len(results) == 5


async def test_rerank_documents_carry_location_head(rerank_on, search_stub, monkeypatch):
    """送进重排的文档带文件路径与符号名——纯代码片段看不出业务归属。"""
    import json

    from app.services.retrieval.service import search_layered

    seen = mock_transport(monkeypatch, ok_handler_n)
    await search_layered("p", "查询", "local", top_k=3)

    docs = json.loads(seen[0].content)["documents"]
    assert docs[0].startswith("src/f0.py :: fn0")
    assert "code 0" in docs[0]


async def test_graph_expansion_still_appends_after_rerank(rerank_on, search_stub, monkeypatch):
    """图扩展在 rerank 之后：结构邻居不该被文本相关性挤掉。"""
    from app.services.retrieval.service import RetrievedItem, search_layered

    search_stub["expanded"] = [
        RetrievedItem(kind="file_summary", node_id="neighbor", file_path="src/other.py",
                      symbol="(file)", symbol_type="file", start_line=0, end_line=0,
                      content="邻居", score=0.0, via_edge="calls_api")
    ]
    mock_transport(monkeypatch, ok_handler_n)

    results = await search_layered("p", "查询", "local", top_k=3)

    assert results[-1].node_id == "neighbor"
    assert len(results) == 4          # 精排的 3 条 + 图扩展 1 条


# ---------------- 实测契约（硅基流动 Qwen3-Reranker-8B 真实响应） ----------------


REAL_RESPONSE = {
    "id": "0198a1c2-real-response-sample",
    "results": [
        {"index": 0, "document": None, "relevance_score": 0.647},
        {"index": 2, "document": None, "relevance_score": 0.042},
        {"index": 1, "document": None, "relevance_score": 0.0002},
    ],
    "meta": {"tokens": {"input_tokens": 260, "output_tokens": 0}},
}

REAL_ERROR_BODY = {"code": 30014, "data": None, "message": "Api key is invalid"}


async def test_real_siliconflow_response_shape(rerank_on, monkeypatch):
    """按实测响应解析：document 回显 null、外层带 id/meta，都不该干扰解析。"""
    mock_transport(monkeypatch, lambda r: httpx.Response(200, json=REAL_RESPONSE))

    ranking = await rerank("查询", ["代码块", "无关 README", "另一段"])

    assert ranking == [(0, 0.647), (2, 0.042), (1, 0.0002)]


def test_real_response_parses_without_client():
    assert parse_ranking(REAL_RESPONSE, 3) == [(0, 0.647), (2, 0.042), (1, 0.0002)]


async def test_error_body_with_200_degrades(rerank_on, monkeypatch):
    """错误响应形如 {"code","data","message"}——没有 results 字段即降级。"""
    mock_transport(monkeypatch, lambda r: httpx.Response(200, json=REAL_ERROR_BODY))
    assert await rerank("q", ["甲", "乙"]) is None


async def test_auth_error_degrades(rerank_on, monkeypatch):
    """key 无效时服务端返回非 2xx + 同样的错误 body。"""
    mock_transport(monkeypatch, lambda r: httpx.Response(401, json=REAL_ERROR_BODY))
    assert await rerank("q", ["甲", "乙"]) is None


async def test_document_field_is_not_requested(rerank_on, monkeypatch):
    """不请求 return_documents——回显文档纯属浪费流量（实测默认就是 null）。"""
    import json

    seen = mock_transport(monkeypatch, lambda r: httpx.Response(200, json=REAL_RESPONSE))
    await rerank("q", ["甲", "乙", "丙"])

    body = json.loads(seen[0].content)
    assert "return_documents" not in body
