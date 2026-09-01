"""增量正确性集成测试（M4 B7 / 设计 D2，需要 Neo4j）。

验收基准是"图等价"：同一变更集下，增量索引与全量重建产出的图必须等价
（同节点集、同边集、同内容 hash），且增量路径中未变更文件保留原 embedding。
这是防止增量随迭代腐化的唯一可靠标准，所以走的是真实 run_index_job + 真实本地 git 仓库。
"""
import shutil
import uuid
from pathlib import Path

import pytest
from git import Repo

from app.graph.client import close_driver, delete_project_graph, ensure_vector_index, get_driver
from app.models.tables import Project
from app.services.ingest.pipeline import MODE_AUTO, MODE_FULL, run_index_job
from tests.helpers.repos import make_source_repo

pytestmark = pytest.mark.integration

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "mini_repo"


def apply_changes(repo: Repo, path: Path) -> str:
    """一次典型改动：改一个后端文件、加一个新文件、删一个前端组件。"""
    orders = path / "backend" / "routers" / "orders.py"
    orders.write_text(
        orders.read_text() + "\n\ndef cancel_order(order_id: int):\n    return {'ok': True}\n"
    )
    (path / "backend" / "services" / "refund_service.py").write_text(
        "def refund(order_id: int):\n    \"\"\"退款服务\"\"\"\n    return True\n"
    )
    (path / "frontend" / "components" / "OrderCard.tsx").unlink()
    repo.git.add(A=True)
    repo.index.commit("change")
    return repo.head.commit.hexsha


async def snapshot(project_id: str) -> dict:
    """图快照：节点集 + 边集 + 内容 hash（不含向量——向量是否复用另行断言）。"""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n {project_id: $pid})
            RETURN labels(n)[0] AS label, n.name AS name, n.path AS path,
                   n.content_hash AS hash, n.symbol AS symbol
            """,
            pid=project_id,
        )
        nodes = {
            (rec["label"], rec["name"], rec["hash"]) async for rec in result
        }
        result = await session.run(
            """
            MATCH (a {project_id: $pid})-[r]->(b)
            RETURN type(r) AS type, a.name AS src, b.name AS dst
            """,
            pid=project_id,
        )
        edges = {(rec["type"], rec["src"], rec["dst"]) async for rec in result}
    return {"nodes": nodes, "edges": edges}


def strip_project_id(snap: dict, pid: str) -> dict:
    """节点名带 project_id 前缀，比较两个项目时要去掉。"""
    def clean(value):
        return value.replace(pid, "<pid>") if isinstance(value, str) else value

    return {
        "nodes": {tuple(clean(v) for v in n) for n in snap["nodes"]},
        "edges": {tuple(clean(v) for v in e) for e in snap["edges"]},
    }


async def chunk_embeddings(project_id: str, file_path: str) -> dict[str, list[float]]:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:Chunk {project_id: $pid, file_path: $path})
            RETURN c.symbol AS symbol, c.embedding AS embedding
            """,
            pid=project_id, path=file_path,
        )
        return {rec["symbol"]: rec["embedding"] async for rec in result}


@pytest.fixture
async def indexing_env(tmp_path, test_db, fake_embedder, fake_summarizer, monkeypatch):
    """真实 run_index_job 所需环境：本地 git 远端 + tmp 仓库目录 + report 打桩。"""
    from app.core.config import settings

    await ensure_vector_index()
    monkeypatch.setattr(settings, "repos_dir", tmp_path / "repos")

    async def fake_report(project_id, llm=None, depth="deep"):
        return {"report_ok": True, "report_partial": False,
                "sequences_ok": 0, "sequences_fallback": 0}

    monkeypatch.setattr(
        "app.services.ingest.pipeline.generate_and_store_report", fake_report
    )

    source = tmp_path / "source"
    repo, first_sha = make_source_repo(source)
    created: list[uuid.UUID] = []

    async def new_project() -> uuid.UUID:
        async with test_db() as session:
            project = Project(name=f"mini-{uuid.uuid4().hex[:6]}", git_url=str(source))
            session.add(project)
            await session.commit()
            await session.refresh(project)
            created.append(project.id)
            return project.id

    async def run(project_id: uuid.UUID, mode: str):
        from app.models.tables import IndexJob

        async with test_db() as session:
            job = IndexJob(project_id=project_id, kind=mode)
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id
        await run_index_job(job_id, project_id, mode)
        async with test_db() as session:
            return await session.get(IndexJob, job_id)

    yield {
        "source": source, "repo": repo, "first_sha": first_sha,
        "new_project": new_project, "run": run, "db": test_db,
    }

    for pid in created:
        await delete_project_graph(str(pid))
    await close_driver()


async def test_incremental_matches_full_rebuild(indexing_env):
    """spec 场景: 同一变更集下增量与强制全量产出的图等价。"""
    incremental_pid = await indexing_env["new_project"]()
    job = await indexing_env["run"](incremental_pid, MODE_FULL)
    assert job.status == "succeeded", job.error_text

    before = await chunk_embeddings(str(incremental_pid), "backend/models.py")
    assert before, "未变更文件应有向量"

    apply_changes(indexing_env["repo"], indexing_env["source"])

    # 增量路径
    job = await indexing_env["run"](incremental_pid, MODE_AUTO)
    assert job.status == "succeeded", job.error_text
    assert job.stats_json["mode"] == "incremental", job.stats_json
    assert job.kind == "incremental"
    incremental_snapshot = strip_project_id(
        await snapshot(str(incremental_pid)), str(incremental_pid)
    )

    # 全量路径（同样的最终工作副本，全新项目）
    full_pid = await indexing_env["new_project"]()
    job = await indexing_env["run"](full_pid, MODE_FULL)
    assert job.status == "succeeded", job.error_text
    full_snapshot = strip_project_id(await snapshot(str(full_pid)), str(full_pid))

    assert incremental_snapshot["nodes"] == full_snapshot["nodes"]
    assert incremental_snapshot["edges"] == full_snapshot["edges"]

    # 未变更文件保留原 embedding（增量的核心收益）
    after = await chunk_embeddings(str(incremental_pid), "backend/models.py")
    assert after == before


async def test_incremental_stats_and_scope(indexing_env):
    """增量只重解析变更文件，未变更文件从图读回。"""
    pid = await indexing_env["new_project"]()
    await indexing_env["run"](pid, MODE_FULL)
    apply_changes(indexing_env["repo"], indexing_env["source"])

    job = await indexing_env["run"](pid, MODE_AUTO)
    stats = job.stats_json

    assert stats["mode"] == "incremental"
    assert stats["reparsed_files"] == 2      # orders.py（改）+ refund_service.py（增）
    assert stats["reused_files"] >= 4        # 其余文件全部复用
    assert stats["deleted_files"] == 2       # OrderCard.tsx（删）+ orders.py（改，先删旧子图）
    assert "fallback_full_reason" not in stats


async def test_deleted_file_leaves_no_residue(indexing_env):
    """spec 场景: 删除的文件在图中不留 File/Chunk 节点及任何边。"""
    pid = await indexing_env["new_project"]()
    await indexing_env["run"](pid, MODE_FULL)
    apply_changes(indexing_env["repo"], indexing_env["source"])
    await indexing_env["run"](pid, MODE_AUTO)

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n {project_id: $pid})
            WHERE n.path = $path OR n.file_path = $path
            RETURN count(n) AS n
            """,
            pid=str(pid), path="frontend/components/OrderCard.tsx",
        )
        assert (await result.single())["n"] == 0

        # 也不能有指向它的悬挂边
        result = await session.run(
            """
            MATCH (a {project_id: $pid})-[r]->(b)
            WHERE b.path = $path OR b.file_path = $path
            RETURN count(r) AS n
            """,
            pid=str(pid), path="frontend/components/OrderCard.tsx",
        )
        assert (await result.single())["n"] == 0


async def test_no_changes_returns_fast_without_touching_graph(indexing_env):
    """spec 场景: 无变更时秒级 succeeded，图不发生写操作。

    M16 起这条路由 ls-remote 判定，连工作区都不建——所以 stats 里不再有
    files_parsed（没走 walk），换成 no_changes_source 标明是哪一层判出来的。
    """
    pid = await indexing_env["new_project"]()
    await indexing_env["run"](pid, MODE_FULL)
    before = await snapshot(str(pid))

    job = await indexing_env["run"](pid, MODE_AUTO)

    assert job.status == "succeeded"
    assert job.stats_json == {
        "mode": "incremental", "no_changes": True, "no_changes_source": "ls-remote",
    }
    assert await snapshot(str(pid)) == before


async def test_auto_falls_back_to_full_on_first_index(indexing_env):
    """spec 场景: 无 last_indexed_commit 时 auto 走全量并说明原因。"""
    pid = await indexing_env["new_project"]()
    job = await indexing_env["run"](pid, MODE_AUTO)

    assert job.status == "succeeded"
    assert job.stats_json["mode"] == "full"
    assert "首次索引" in job.stats_json["fallback_full_reason"]


async def test_project_node_records_embedding_model(indexing_env):
    """M4 B15：Project 节点记录本次索引用的嵌入模型。"""
    from app.core.config import settings

    pid = await indexing_env["new_project"]()
    await indexing_env["run"](pid, MODE_FULL)

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Project {project_id: $pid})
            RETURN p.embedding_model AS model, p.embedding_dim AS dim
            """,
            pid=str(pid),
        )
        record = await result.single()

    assert record["model"] == settings.embedding_model
    assert record["dim"] == settings.embedding_dim


async def test_embedding_model_change_forces_full_rebuild(indexing_env, monkeypatch):
    """M4 B15：换嵌入模型后 auto 必须转全量，否则未变更文件留着旧模型向量。"""
    from app.core.config import settings

    pid = await indexing_env["new_project"]()
    await indexing_env["run"](pid, MODE_FULL)
    before = await chunk_embeddings(str(pid), "backend/models.py")

    apply_changes(indexing_env["repo"], indexing_env["source"])
    monkeypatch.setattr(settings, "embedding_model", "some-other-model")

    job = await indexing_env["run"](pid, MODE_AUTO)

    assert job.status == "succeeded", job.error_text
    assert job.stats_json["mode"] == "full"
    assert job.stats_json["fallback_full_reason"] == "embedding_model_changed"
    # 全量重嵌入：未变更文件的向量也被重算（缓存键含模型名，旧键全部失效）
    assert job.stats_json["embedded_cached"] == 0
    assert await chunk_embeddings(str(pid), "backend/models.py") != {}
    # 新模型标识已写回，下次同配置的 auto 可以正常增量
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (p:Project {project_id: $pid}) RETURN p.embedding_model AS m",
            pid=str(pid),
        )
        assert (await result.single())["m"] == "some-other-model"
    assert before  # 前置断言：改动前确实有向量


async def test_legacy_nodes_without_imports_property(indexing_env):
    """Migration: M4 之前写入的 File 节点没有 imports 属性，增量时现场重提取。"""
    pid = await indexing_env["new_project"]()
    await indexing_env["run"](pid, MODE_FULL)

    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (f:File {project_id: $pid}) REMOVE f.imports", pid=str(pid)
        )
    before = await snapshot(str(pid))

    apply_changes(indexing_env["repo"], indexing_env["source"])
    job = await indexing_env["run"](pid, MODE_AUTO)

    assert job.status == "succeeded", job.error_text
    assert job.stats_json["mode"] == "incremental"
    assert job.stats_json["imports_restored"] >= 1

    # 重提取后 IMPORTS 边完好（属性丢失不会退化成 shared 归属）
    after = await snapshot(str(pid))
    legacy_import_edges = {e for e in before["edges"] if e[0] == "IMPORTS"}
    restored_import_edges = {e for e in after["edges"] if e[0] == "IMPORTS"}
    kept = {e for e in legacy_import_edges if "OrderCard" not in e[1] + e[2]}
    assert kept <= restored_import_edges


async def test_last_indexed_commit_updated_only_on_success(indexing_env):
    pid = await indexing_env["new_project"]()
    await indexing_env["run"](pid, MODE_FULL)

    async with indexing_env["db"]() as session:
        project = await session.get(Project, pid)
        assert project.last_indexed_commit == indexing_env["first_sha"]
        assert project.status == "ready"

    new_sha = apply_changes(indexing_env["repo"], indexing_env["source"])
    await indexing_env["run"](pid, MODE_AUTO)

    async with indexing_env["db"]() as session:
        project = await session.get(Project, pid)
        assert project.last_indexed_commit == new_sha
