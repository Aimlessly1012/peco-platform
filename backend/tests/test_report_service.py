"""M3 报告编排与 pipeline 接入单测（B4）：upsert 覆盖写、失败不阻塞、partial 归因。"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models.tables import IndexDepth, Project, UnderstandingReport
from app.services.ingest.pipeline import partial_reason
from app.services.report.graph_reader import GraphEdges, ModuleEdge, ProjectTree
from app.services.report.service import generate_and_store_report
from tests.test_report import GOOD_SEQ, FakeLLM, make_edges, make_tree


@pytest.fixture
def stub_graph(monkeypatch):
    """打桩图读取，使报告编排无需 Neo4j。"""
    state = {
        "tree": make_tree(),
        "edges": make_edges(),
        "module_edges": [
            ModuleEdge(
                src_key="page:orders", src_name="orders", src_kind="page",
                dst_key="api:orders", dst_name="orders", dst_kind="api",
                relation="calls_api", count=3,
            )
        ],
    }

    async def fake_tree(project_id: str):
        if isinstance(state["tree"], Exception):
            raise state["tree"]
        return state["tree"]

    async def fake_edges(project_id: str):
        return state["edges"]

    async def fake_module_edges(project_id: str):
        return state["module_edges"]

    async def fake_anchors(project_id: str, **kwargs):
        return state["anchors"]

    async def fake_feature_cache(project_id: str):
        return dict(state["feature_cache"])

    async def fake_save_features(project_id: str, points_by_hash: dict):
        state["saved_features"] = points_by_hash
        return len(points_by_hash)

    state["anchors"] = {
        "api:orders": ["backend/routers/orders.py（create_order, list_orders）"],
        "page:orders": ["frontend/pages/orders.tsx（OrdersPage）"],
    }
    state["feature_cache"] = {}
    state["saved_features"] = {}
    monkeypatch.setattr("app.services.report.service.read_project_tree", fake_tree)
    monkeypatch.setattr("app.services.report.service.read_graph_edges", fake_edges)
    monkeypatch.setattr("app.services.report.service.read_module_edges", fake_module_edges)
    monkeypatch.setattr("app.services.report.service.read_module_anchors", fake_anchors)
    monkeypatch.setattr("app.services.report.service.load_feature_cache", fake_feature_cache)
    monkeypatch.setattr("app.services.report.service.save_module_features", fake_save_features)
    return state


async def _new_project(test_db) -> uuid.UUID:
    async with test_db() as session:
        project = Project(name="mini-shop", git_url="https://example.com/x.git")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project.id


async def _load_report(test_db, pid) -> UnderstandingReport | None:
    async with test_db() as session:
        return await session.scalar(
            select(UnderstandingReport).where(UnderstandingReport.project_id == pid)
        )


async def test_generate_and_store_writes_all_four(test_db, stub_graph):
    """M5 spec 场景: deep 索引产出报告四件（文档/导图/数据流图/时序图）。"""
    pid = await _new_project(test_db)
    llm = FakeLLM(chapter_returns="### 章节\n正文", seq_returns=[GOOD_SEQ, GOOD_SEQ])

    stats = await generate_and_store_report(pid, llm=llm)

    assert stats["report_ok"] is True
    assert stats["report_partial"] is False
    assert (stats["sequences_ok"], stats["sequences_fallback"]) == (2, 0)
    assert stats["report_modules"] == 4
    assert stats["report_depth"] == IndexDepth.DEEP
    assert stats["dataflow_edges"] == 1

    report = await _load_report(test_db, pid)
    assert report.doc_markdown.startswith("# mini-shop 需求逻辑文档")
    assert "### 章节" in report.doc_markdown
    assert report.mindmap_mermaid.startswith("mindmap")
    assert report.dataflow_mermaid.startswith("flowchart LR")
    assert len(report.sequences_json) == 2
    assert all(s["mermaid"] for s in report.sequences_json)


async def test_fast_depth_produces_only_programmatic_artifacts(test_db, stub_graph):
    """M5 spec: fast 报告只有程序化两件，且不调 LLM。"""
    pid = await _new_project(test_db)
    llm = FakeLLM(chapter_returns="### 不该被调用", seq_returns=[GOOD_SEQ])

    stats = await generate_and_store_report(pid, llm=llm, depth=IndexDepth.FAST)

    assert stats["report_ok"] is True
    assert stats["report_depth"] == IndexDepth.FAST
    assert llm.chapter_calls == [] and llm.seq_calls == [] and llm.overview_calls == []

    report = await _load_report(test_db, pid)
    assert report.mindmap_mermaid.startswith("mindmap")
    assert report.dataflow_mermaid.startswith("flowchart LR")
    assert report.doc_markdown == ""
    assert report.sequences_json == []


async def test_partial_when_sequence_falls_back(test_db, stub_graph):
    """单张时序图两次失败 → 记 fallback，任务标 partial（但报告仍写入）。"""
    pid = await _new_project(test_db)
    llm = FakeLLM(chapter_returns="### 章节", seq_returns=[GOOD_SEQ, "非法", "仍非法"])

    stats = await generate_and_store_report(pid, llm=llm)

    assert stats["report_ok"] is True
    assert stats["report_partial"] is True
    assert (stats["sequences_ok"], stats["sequences_fallback"]) == (1, 1)

    report = await _load_report(test_db, pid)
    fallen = [s for s in report.sequences_json if not s["mermaid"]]
    assert len(fallen) == 1 and fallen[0]["fallback_text"]


async def test_doc_fallback_marks_partial(test_db, stub_graph):
    pid = await _new_project(test_db)
    llm = FakeLLM(chapter_returns=None, seq_returns=[GOOD_SEQ, GOOD_SEQ])

    stats = await generate_and_store_report(pid, llm=llm)

    assert stats["doc_fallback"] is True
    assert stats["report_partial"] is True
    report = await _load_report(test_db, pid)
    assert report.doc_markdown.startswith("# mini-shop 需求逻辑文档")


async def test_graph_read_failure_does_not_raise(test_db, stub_graph):
    """spec: report 阶段任何失败都不得阻塞索引成功。"""
    pid = await _new_project(test_db)
    stub_graph["tree"] = RuntimeError("Neo4j 连接失败")

    stats = await generate_and_store_report(pid, llm=FakeLLM())

    assert stats["report_ok"] is False
    assert stats["report_partial"] is True
    assert "Neo4j 连接失败" in stats["report_error"]
    assert (stats["sequences_ok"], stats["sequences_fallback"]) == (0, 0)
    assert await _load_report(test_db, pid) is None


async def test_upsert_overwrites_single_row(test_db, stub_graph):
    """设计 D3: 一项目一行，重索引覆盖写。"""
    pid = await _new_project(test_db)
    await generate_and_store_report(
        pid, llm=FakeLLM(chapter_returns="### 第一版", seq_returns=[GOOD_SEQ, GOOD_SEQ])
    )
    first = await _load_report(test_db, pid)

    await generate_and_store_report(
        pid, llm=FakeLLM(chapter_returns="### 第二版", seq_returns=[GOOD_SEQ, GOOD_SEQ])
    )

    async with test_db() as session:
        count = await session.scalar(
            select(func.count()).select_from(UnderstandingReport).where(
                UnderstandingReport.project_id == pid
            )
        )
    assert count == 1
    second = await _load_report(test_db, pid)
    assert second.id == first.id  # 同一行被覆盖，不是删旧建新
    assert "### 第二版" in second.doc_markdown
    assert "### 第一版" not in second.doc_markdown


async def test_empty_graph_still_produces_report(test_db, stub_graph):
    """图里没有模块（如索引未产出）时思维导图仍必定生成，不报错。"""
    pid = await _new_project(test_db)
    stub_graph["tree"] = ProjectTree(project_id=str(pid), name="空项目")
    stub_graph["edges"] = GraphEdges()

    stats = await generate_and_store_report(pid, llm=FakeLLM(chapter_returns="### 空"))

    assert stats["report_ok"] is True
    assert (stats["sequences_ok"], stats["sequences_fallback"]) == (0, 0)
    report = await _load_report(test_db, pid)
    assert report.mindmap_mermaid.startswith("mindmap")
    assert report.sequences_json == []


# ---------------- pipeline partial 归因（B4） ----------------


@pytest.mark.parametrize(
    "summary_partial,report_stats,expect",
    [
        (False, {"report_ok": True, "report_partial": False}, None),
        (True, {"report_ok": True, "report_partial": False}, "部分摘要生成失败"),
        (False, {"report_ok": True, "report_partial": True}, "部分报告内容已降级"),
        (False, {"report_ok": False, "report_partial": True, "report_error": "X: y"},
         "理解报告生成失败：X: y"),
    ],
)
def test_partial_reason(summary_partial, report_stats, expect):
    reason = partial_reason(summary_partial, report_stats)
    if expect is None:
        assert reason is None
    else:
        assert expect in reason and reason.endswith("（partial）")


def test_partial_reason_merges_both_sources():
    reason = partial_reason(True, {"report_partial": True})
    assert "部分摘要生成失败" in reason
    assert "部分报告内容已降级" in reason
