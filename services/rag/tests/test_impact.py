"""影响面多跳单测（M4 B8/B9）：分层格式化与 impact 检索策略。

真实多跳遍历见 test_impact_integration.py（需要 Neo4j）。
"""
import pytest

from app.services.qa.workflow import SYSTEM_PROMPT, UNDERSTAND_PROMPT, retrieve_node
from app.services.retrieval.service import RetrievedItem, format_impact_context


def make_impact(**overrides) -> dict:
    base = {
        "target": "backend/services/order_service.py",
        "resolved_files": ["backend/services/order_service.py"],
        "max_depth": 3,
        "direct": [
            {"file_path": "backend/routers/orders.py", "summary": "订单路由",
             "depth": 1, "via_path": ["backend/routers/orders.py",
                                      "backend/services/order_service.py"]},
        ],
        "transitive": [
            {"file_path": "backend/main.py", "summary": "应用入口", "depth": 2,
             "via_path": ["backend/main.py", "backend/routers/orders.py",
                          "backend/services/order_service.py"]},
        ],
        "frontend_callers": [
            {"file_path": "frontend/pages/orders.tsx", "symbol": "OrdersPage",
             "lines": "5-30", "calls": "backend/routers/orders.py:create_order"},
        ],
        "modules_affected": [
            {"name": "orders", "kind": "api", "route_prefix": "/api/orders",
             "affected_files": 3},
        ],
        "truncated": False,
    }
    return {**base, **overrides}


def test_format_impact_context_is_layered():
    text = format_impact_context(make_impact())

    assert "直接引用它的文件：" in text
    assert "backend/routers/orders.py" in text
    assert "间接受影响的文件（按传播深度）：" in text
    assert "[2 跳] backend/main.py" in text
    # 传播路径按"从被改文件出发"的方向展示，便于人读
    assert "backend/services/order_service.py → backend/routers/orders.py → backend/main.py" in text
    assert "经 HTTP 调用受影响接口的前端代码块：" in text
    assert "波及的功能模块：" in text
    assert "[api] orders（路由 /api/orders）：3 个文件" in text


def test_format_impact_context_when_nothing_depends_on_it():
    text = format_impact_context(
        make_impact(direct=[], transitive=[], frontend_callers=[])
    )
    assert "未发现其他文件引用它" in text


def test_format_impact_context_marks_truncation():
    text = format_impact_context(make_impact(truncated=True))
    assert "已截断" in text


def test_prompts_cover_impact():
    assert "impact" in UNDERSTAND_PROMPT
    assert "会影响哪些地方" in UNDERSTAND_PROMPT
    assert "【影响面分析】" in SYSTEM_PROMPT
    assert "分层回答" in SYSTEM_PROMPT


# ---------------- impact 检索策略 ----------------


def chunk_item(path: str, symbol: str = "fn") -> RetrievedItem:
    return RetrievedItem(
        kind="chunk", node_id=f"n:{path}:{symbol}", file_path=path, symbol=symbol,
        symbol_type="function", start_line=1, end_line=9, content="code", score=0.9,
    )


@pytest.fixture
def retrieval_stub(monkeypatch):
    state = {
        "items": [chunk_item("backend/services/order_service.py")],
        "impact": make_impact(),
        "calls": [],
    }

    async def fake_search(pid, question, question_type="local", top_k=None):
        state["calls"].append({"type": question_type})
        return state["items"]

    async def fake_impact(pid, file_or_symbol, max_depth=2):
        if isinstance(state["impact"], Exception):
            raise state["impact"]
        state["calls"].append({"impact_target": file_or_symbol, "max_depth": max_depth})
        return state["impact"]

    monkeypatch.setattr("app.services.qa.workflow.search_layered", fake_search)
    monkeypatch.setattr("app.services.qa.workflow.impact_of", fake_impact)
    return state


async def test_retrieve_impact_adds_unnumbered_block(retrieval_stub):
    """影响树作为无编号背景资料——编号必须留给 items，否则 [n] 与 citations 错位。"""
    out = await retrieve_node(
        {"project_id": "p", "question": "改 order_service 影响什么", "question_type": "impact"}
    )

    context = out["context_text"]
    assert context.startswith("### 【影响面分析】（背景信息，无编号，不要标注）")
    assert "直接引用它的文件：" in context
    # items 仍从「资料 1」开始编号，与 citations 下标一一对应
    assert "### 资料 1:" in context
    assert "### 资料 2:" not in context
    assert len(out["items"]) == 1


async def test_retrieve_impact_uses_top_hit_as_target(retrieval_stub):
    await retrieve_node(
        {"project_id": "p", "question": "改它影响什么", "question_type": "impact"}
    )
    impact_call = next(c for c in retrieval_stub["calls"] if "impact_target" in c)
    assert impact_call["impact_target"] == "backend/services/order_service.py"
    assert impact_call["max_depth"] == 3
    # M7：impact 透传到检索层（据此跳过 rerank），检索策略内部仍等同 local
    assert retrieval_stub["calls"][0]["type"] == "impact"


async def test_retrieve_impact_degrades_when_no_target(retrieval_stub):
    """spec 场景: 定位不到目标文件时退化为 local 回答，不报错。"""
    retrieval_stub["items"] = []

    out = await retrieve_node(
        {"project_id": "p", "question": "改它影响什么", "question_type": "impact"}
    )

    assert "【影响面分析】" not in out["context_text"]
    assert out["items"] == []
    assert not any("impact_target" in c for c in retrieval_stub["calls"])


async def test_retrieve_impact_degrades_when_query_fails(retrieval_stub):
    """影响面查询本身失败也只降级，不能让问答挂掉。"""
    retrieval_stub["impact"] = RuntimeError("Neo4j 超时")

    out = await retrieve_node(
        {"project_id": "p", "question": "改它影响什么", "question_type": "impact"}
    )

    assert "【影响面分析】" not in out["context_text"]
    assert "### 资料 1:" in out["context_text"]  # 常规资料仍在


async def test_retrieve_local_unaffected(retrieval_stub):
    out = await retrieve_node(
        {"project_id": "p", "question": "create_order 在哪", "question_type": "local"}
    )
    assert "【影响面分析】" not in out["context_text"]
    assert out["context_text"].startswith("### 资料 1:")
