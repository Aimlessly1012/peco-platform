"""M3 报告与功能地图 API 单测（B5）：sqlite 内存库 + Neo4j 读取打桩。"""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.tables import Project, ProjectStatus, UnderstandingReport
from tests.helpers.report import make_tree

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
                    dataflow_mermaid='flowchart LR\n    n0["[接口] orders"]',
                    feature_map_markdown="# mini-shop：订单管理系统\n\n## orders\n- 创建订单\n",
                    business_flows_json=[
                        {"title": "下单流程",
                         "mermaid": "flowchart TD\n    A[下单] --> B[支付]",
                         "fallback_text": ""}
                    ],
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


async def test_get_report_returns_four_artifacts(api_client, test_db):
    pid = await _make_project(test_db, with_report=True)
    resp = await api_client.get(f"/projects/{pid}/report")

    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == str(pid)
    assert body["doc_markdown"].startswith("# mini-shop")
    assert body["mindmap_mermaid"].startswith("mindmap")
    assert body["feature_map_markdown"].startswith("# mini-shop：")
    assert "## orders" in body["feature_map_markdown"]
    assert body["business_flows"][0]["title"] == "下单流程"
    assert body["business_flows"][0]["mermaid"].startswith("flowchart TD")
    assert body["dataflow_mermaid"].startswith("flowchart LR")
    assert body["depth"] == "deep"
    assert len(body["sequences"]) == 2
    assert body["sequences"][0]["mermaid"].startswith("sequenceDiagram")
    # 降级的那张图 mermaid 为空但 fallback_text 有内容（前端据此兜底）
    assert body["sequences"][1]["mermaid"] == ""
    assert body["sequences"][1]["fallback_text"]
    assert body["generated_at"]


async def test_legacy_report_without_dataflow(api_client, test_db):
    """M5 迁移: 旧报告没有 dataflow_mermaid（NULL），API 返回空串供前端隐藏卡片。"""
    async with test_db() as session:
        project = Project(name="old", git_url="https://example.com/x.git",
                          status=ProjectStatus.READY)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        session.add(
            UnderstandingReport(
                project_id=project.id, doc_markdown="# 旧报告",
                mindmap_mermaid="mindmap\n  root((x))",
                dataflow_mermaid=None, sequences_json=[],
                generated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        pid = project.id

    body = (await api_client.get(f"/projects/{pid}/report")).json()
    assert body["dataflow_mermaid"] == ""
    # M6 迁移: 旧报告没有功能导图与业务流程图，前端回退渲染 mindmap_mermaid
    assert body["feature_map_markdown"] == ""
    assert body["business_flows"] == []
    assert body["mindmap_mermaid"].startswith("mindmap")
    assert body["depth"] == "deep"


async def test_fast_report_is_marked_for_upgrade(api_client, test_db):
    """fast 产物没有文档正文 → depth=fast，前端据此显示「生成深度理解」。"""
    async with test_db() as session:
        project = Project(name="fast-p", git_url="https://example.com/x.git",
                          status=ProjectStatus.READY, index_depth="fast")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        session.add(
            UnderstandingReport(
                project_id=project.id, doc_markdown="",
                mindmap_mermaid="mindmap\n  root((x))",
                dataflow_mermaid="flowchart LR\n    n0[\"a\"]",
                sequences_json=[], generated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        pid = project.id

    body = (await api_client.get(f"/projects/{pid}/report")).json()
    assert body["depth"] == "fast"
    assert body["doc_markdown"] == ""
    assert body["dataflow_mermaid"].startswith("flowchart LR")


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
