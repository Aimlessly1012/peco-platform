"""答案 [n] 上标引用的编号一致性（PM 增补项）。

核心不变量：提示词里的「### 资料 N:」编号 ↔ SSE citations 数组下标 N-1，
两边必须同序等长，否则前端 SOURCES 会错位。
"""
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.tables import ChatMessage, ChatSession, Project, ProjectStatus
from app.services.qa.workflow import SYSTEM_PROMPT, _format_item
from app.services.retrieval.service import RetrievedItem


def make_items() -> list[RetrievedItem]:
    """直接命中与关联带出交错——错位问题只在交错时暴露。"""
    return [
        RetrievedItem(
            kind="chunk", node_id="n1", file_path="backend/routers/orders.py",
            symbol="create_order", symbol_type="function",
            start_line=40, end_line=58, content="def create_order(): ...", score=0.9,
        ),
        RetrievedItem(
            kind="file_summary", node_id="n2", file_path="backend/services/order_service.py",
            symbol="(file)", symbol_type="file", start_line=0, end_line=0,
            content="订单服务：落库与校验", score=0.5, via_edge="imports",
        ),
        RetrievedItem(
            kind="chunk", node_id="n3", file_path="frontend/pages/orders.tsx",
            symbol="OrdersPage", symbol_type="component",
            start_line=5, end_line=30, content="export default function OrdersPage() {}",
            score=0.4,
        ),
        RetrievedItem(
            kind="module_summary", node_id="n4", file_path="", symbol="orders",
            symbol_type="module", start_line=0, end_line=0,
            content="订单模块：下单与查询", score=0.3,
        ),
    ]


def test_citation_carries_kind_and_via_edge():
    items = make_items()
    direct, related = items[0].citation(), items[1].citation()

    assert direct["kind"] == "chunk"
    assert direct["via_edge"] is None
    assert direct["file_path"] == "backend/routers/orders.py"
    assert (direct["start_line"], direct["end_line"]) == (40, 58)

    assert related["via_edge"] == "imports"  # 前端据此弱化展示关联带出项
    assert items[3].citation()["file_path"] == "[模块] orders"  # 模块无文件路径


def test_context_numbering_matches_citation_index():
    """资料 N ↔ citations[N-1]：这是 [n] 上标能对上的唯一依据。"""
    items = make_items()
    parts = [_format_item(i + 1, item) for i, item in enumerate(items)]
    citations = [item.citation() for item in items]

    assert len(parts) == len(citations)
    for i, (part, citation) in enumerate(zip(parts, citations), start=1):
        assert part.startswith(f"### 资料 {i}:")
        # 编号对应的那条资料，其文件路径必须出现在同序的 citation 里
        assert citation["file_path"].removeprefix("[模块] ") in part


def test_related_items_are_numbered_and_marked():
    """关联带出项同样占编号（否则后续资料编号会整体前移）。"""
    items = make_items()
    part = _format_item(2, items[1])
    assert part.startswith("### 资料 2:")
    assert "关联带出" in part


def test_system_prompt_defines_bracket_rule():
    assert "[n]" in SYSTEM_PROMPT
    assert "资料 N" in SYSTEM_PROMPT
    assert "不要罗列全部编号" in SYSTEM_PROMPT
    assert "【项目总览】" in SYSTEM_PROMPT  # 无编号的背景块要显式排除


# ---------------- SSE 端到端 ----------------


class FakeGraph:
    """按真实事件顺序回放：retrieve 结束 → 答案 token。"""

    def __init__(self, items, answer="订单创建在 [1]，前端入口见 [3]。"):
        self.items = items
        self.answer = answer

    async def astream_events(self, inputs, version=None):
        yield {
            "event": "on_chain_end",
            "name": "retrieve",
            "data": {"output": {"items": self.items}},
        }
        for token in (self.answer[:6], self.answer[6:]):
            yield {
                "event": "on_chat_model_stream",
                "tags": ["answer"],
                "data": {"chunk": SimpleNamespace(content=token)},
            }
        # 内部节点的流不得混进答案
        yield {
            "event": "on_chat_model_stream",
            "tags": ["internal"],
            "data": {"chunk": SimpleNamespace(content="（改写结果，不应出现）")},
        }


def _sse_event(text: str, name: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"event: {name}":
            for follow in lines[i + 1:]:
                if follow.startswith("data:"):
                    return follow[len("data:"):].strip()
    raise AssertionError(f"SSE 中没有 {name} 事件：{text[:300]}")


@pytest.fixture
async def chat_session_id(test_db):
    async with test_db() as session:
        project = Project(
            name="mini-shop", git_url="https://example.com/x.git",
            status=ProjectStatus.READY,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        chat = ChatSession(project_id=project.id, title="t")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        return chat.id


async def test_sse_citations_align_with_numbering(
    api_client, test_db, chat_session_id, monkeypatch
):
    items = make_items()
    monkeypatch.setattr("app.api.chat.qa_graph", FakeGraph(items))

    resp = await api_client.post(
        f"/sessions/{chat_session_id}/ask", json={"question": "订单怎么创建"}
    )
    assert resp.status_code == 200

    citations = json.loads(_sse_event(resp.text, "citations"))
    assert len(citations) == len(items)  # 关联带出项没有被过滤掉
    assert [c["node_id"] for c in citations] == [i.node_id for i in items]
    assert citations[1]["via_edge"] == "imports"
    # 答案里的 [3] 能在 citations 中定位到第 3 条
    assert citations[2]["file_path"] == "frontend/pages/orders.tsx"


async def test_answer_and_citations_persisted(
    api_client, test_db, chat_session_id, monkeypatch
):
    items = make_items()
    monkeypatch.setattr("app.api.chat.qa_graph", FakeGraph(items))

    await api_client.post(
        f"/sessions/{chat_session_id}/ask", json={"question": "订单怎么创建"}
    )

    async with test_db() as session:
        rows = list(
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat_session_id)
                .order_by(ChatMessage.created_at)
            )
        )
    answer = next(m for m in rows if m.role == "assistant")
    assert answer.content == "订单创建在 [1]，前端入口见 [3]。"
    assert "不应出现" not in answer.content  # internal 流被过滤
    # 落库的 citations 与 SSE 同序同长，历史消息重放时上标仍能对上
    assert [c["node_id"] for c in answer.citations_json] == [i.node_id for i in items]


async def test_ask_rejects_not_ready_project(api_client, test_db, monkeypatch):
    async with test_db() as session:
        project = Project(
            name="building", git_url="https://example.com/x.git",
            status=ProjectStatus.INDEXING,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        chat = ChatSession(project_id=project.id, title="t")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        sid = chat.id

    resp = await api_client.post(f"/sessions/{sid}/ask", json={"question": "x"})
    assert resp.status_code == 409


async def test_ask_unknown_session(api_client, test_db):
    resp = await api_client.post(f"/sessions/{uuid.uuid4()}/ask", json={"question": "x"})
    assert resp.status_code == 404
