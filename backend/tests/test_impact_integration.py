"""影响面多跳集成测试（M4 B8，需要 Neo4j）：真实反向 IMPORTS 遍历与深度分层。

mini_repo 的依赖链：orders.tsx → api.ts、orders.py → order_service.py、main.py → routers/*，
足以断言"被多层 import 的基础服务"这类场景的分层正确性。
"""
import uuid

import pytest

from app.graph.client import close_driver, delete_project_graph, ensure_vector_index
from app.services.retrieval.service import MAX_IMPACT_DEPTH, impact_of
from tests.test_pipeline_integration import _index_fixture

pytestmark = pytest.mark.integration


@pytest.fixture
async def indexed(fake_embedder, fake_summarizer):
    await ensure_vector_index()
    pid = f"test-{uuid.uuid4().hex[:8]}"
    await _index_fixture(pid, fake_embedder, fake_summarizer)
    yield pid
    await delete_project_graph(pid)
    await close_driver()


async def test_direct_importers_at_depth_one(indexed):
    impact = await impact_of(indexed, "backend/services/order_service.py", max_depth=1)

    assert impact["resolved_files"] == ["backend/services/order_service.py"]
    direct = {row["file_path"] for row in impact["direct"]}
    assert "backend/routers/orders.py" in direct
    assert all(row["depth"] == 1 for row in impact["direct"])
    assert impact["transitive"] == []  # 深度 1 不产出间接层


async def test_transitive_importers_carry_depth_and_path(indexed):
    """spec 场景: 被多层 import 的文件按深度分层，间接项带传播路径。"""
    impact = await impact_of(indexed, "backend/services/order_service.py", max_depth=3)

    assert {row["file_path"] for row in impact["direct"]} == {"backend/routers/orders.py"}
    transitive = {row["file_path"]: row for row in impact["transitive"]}
    assert "backend/main.py" in transitive  # main → routers/orders → order_service

    row = transitive["backend/main.py"]
    assert row["depth"] == 2
    assert row["via_path"][0] == "backend/main.py"
    assert row["via_path"][-1] == "backend/services/order_service.py"
    # 同一文件只出现在一个层级（取最短路径）
    assert not (set(transitive) & {r["file_path"] for r in impact["direct"]})


async def test_depth_is_clamped(indexed):
    deep = await impact_of(indexed, "backend/services/order_service.py", max_depth=99)
    assert deep["max_depth"] == MAX_IMPACT_DEPTH

    shallow = await impact_of(indexed, "backend/services/order_service.py", max_depth=0)
    assert shallow["max_depth"] == 1


async def test_frontend_callers_and_modules(indexed):
    """spec 场景: 波及前端调用方与模块聚合。"""
    impact = await impact_of(indexed, "backend/routers/orders.py", max_depth=3)

    callers = {row["file_path"] for row in impact["frontend_callers"]}
    assert callers, "应能查到经 CALLS_API 调用该 handler 的前端块"
    assert all("-" in row["lines"] for row in impact["frontend_callers"])

    modules = {row["name"] for row in impact["modules_affected"]}
    assert modules
    assert all(row["affected_files"] >= 1 for row in impact["modules_affected"])


async def test_symbol_resolves_to_defining_file(indexed):
    impact = await impact_of(indexed, "create_order", max_depth=2)
    assert impact["resolved_files"] == ["backend/routers/orders.py"]


async def test_unknown_target_returns_empty_shape(indexed):
    impact = await impact_of(indexed, "no/such/file.py", max_depth=2)

    assert impact["resolved_files"] == []
    assert impact["direct"] == [] and impact["transitive"] == []
    assert impact["frontend_callers"] == [] and impact["modules_affected"] == []
    assert impact["truncated"] is False


async def test_leaf_file_has_no_dependents(indexed):
    """入口文件没人 import 它——不能报错，要如实返回空。"""
    impact = await impact_of(indexed, "backend/main.py", max_depth=3)
    assert impact["resolved_files"] == ["backend/main.py"]
    assert impact["direct"] == []


async def test_project_isolation(indexed, fake_embedder, fake_summarizer):
    other = f"test-{uuid.uuid4().hex[:8]}"
    try:
        await _index_fixture(other, fake_embedder, fake_summarizer)
        impact = await impact_of(indexed, "backend/services/order_service.py", max_depth=3)
        # 另一个项目有同名文件，但结果里不能混入（所有查询按 project_id 过滤）
        assert impact["direct"], "本项目内仍应查到引用者"
        by_depth = impact["direct"] + impact["transitive"]
        assert len(by_depth) == len({row["file_path"] for row in by_depth})
    finally:
        await delete_project_graph(other)
