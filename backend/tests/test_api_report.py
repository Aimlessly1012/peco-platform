"""M3 报告与功能地图 API 单测（B5）：sqlite 内存库 + Neo4j 读取打桩。"""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.tables import Project, ProjectStatus, UnderstandingReport
from tests.test_report import make_tree

SEQUENCES = [
    {
        "module_key": "api:orders", "module_name": "orders", "kind": "api",
        "route_prefix": "/api/orders",
        "mermaid": "sequenceDiagram\n    A->>B: x", "fallback_text": "文字链路",
    },
    {
        "module_key": "page:orders", "module_name": "orders", "kind": "page",
        "route_prefix": "/orders",
        "mermaid": "", "fallback_text": "该模块时序图降级为文字链路",
    },
]


async def _make_project(test_db, *, with_report=False) -> uuid.UUID:
    async with test_db() as session:
        project = Project(
            name="mini-shop", git_url="https://example.com/x.git",
            status=ProjectStatus.READY,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        pid = project.id
        if with_report:
            session.add(
                UnderstandingReport(
                    project_id=pid,
                    doc_markdown="# mini-shop 需求逻辑文档\n正文",
                    mindmap_mermaid="mindmap\n  root((mini-shop))",
                    sequences_json=SEQUENCES,
                    generated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
    return pid


@pytest.fixture
def stub_tree(monkeypatch):
    """打桩 Neo4j 读取，使 /modules 无需真实图数据库。"""
    tree = make_tree()

    async def fake_read(project_id: str):
        return tree

    monkeypatch.setattr("app.api.projects.read_project_tree", fake_read)
    return tree


async def test_get_report_returns_triplet(api_client, test_db):
    pid = await _make_project(test_db, with_report=True)
    resp = await api_client.get(f"/projects/{pid}/report")

    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == str(pid)
    assert body["doc_markdown"].startswith("# mini-shop")
    assert body["mindmap_mermaid"].startswith("mindmap")
    assert len(body["sequences"]) == 2
    assert body["sequences"][0]["mermaid"].startswith("sequenceDiagram")
    # 降级的那张图 mermaid 为空但 fallback_text 有内容（前端据此兜底）
    assert body["sequences"][1]["mermaid"] == ""
    assert body["sequences"][1]["fallback_text"]
    assert body["generated_at"]


async def test_get_report_404_hints_reindex(api_client, test_db):
    """spec 场景: 旧项目无报告 → 404 + 请重新索引提示。"""
    pid = await _make_project(test_db)
    resp = await api_client.get(f"/projects/{pid}/report")

    assert resp.status_code == 404
    assert "重新索引" in resp.json()["detail"]


async def test_get_report_unknown_project_404(api_client, test_db):
    resp = await api_client.get(f"/projects/{uuid.uuid4()}/report")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "项目不存在"


async def test_get_modules_reads_graph(api_client, test_db, stub_tree):
    pid = await _make_project(test_db)
    resp = await api_client.get(f"/projects/{pid}/modules")

    assert resp.status_code == 200
    body = resp.json()
    assert body["project_name"] == "mini-shop"
    assert body["project_summary"] == "全栈演示项目：订单与用户"
    assert len(body["modules"]) == len(stub_tree.modules)

    orders_api = next(m for m in body["modules"] if m["key"] == "api:orders")
    assert orders_api["kind"] == "api"
    assert orders_api["route_prefix"] == "/api/orders"
    assert orders_api["summary"].startswith("订单接口模块")
    paths = [f["path"] for f in orders_api["files"]]
    assert "backend/routers/orders.py" in paths
    # L2 文件摘要随文件清单一起返回（前端展开即用）
    assert all(f["summary"] for f in orders_api["files"])


async def test_get_modules_empty_graph(api_client, test_db, monkeypatch):
    """未索引项目：图中无数据 → 200 + 空模块列表（由前端引导索引）。"""
    from app.services.report.graph_reader import ProjectTree

    async def fake_read(project_id: str):
        return ProjectTree(project_id=project_id)

    monkeypatch.setattr("app.api.projects.read_project_tree", fake_read)
    pid = await _make_project(test_db)
    resp = await api_client.get(f"/projects/{pid}/modules")

    assert resp.status_code == 200
    assert resp.json()["modules"] == []
    assert resp.json()["project_name"] == "mini-shop"  # 回退用 Postgres 里的项目名


async def test_get_modules_unknown_project_404(api_client, test_db, stub_tree):
    resp = await api_client.get(f"/projects/{uuid.uuid4()}/modules")
    assert resp.status_code == 404
