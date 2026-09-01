"""索引深度模式单测（M5 B8）：API 贯通、fast 零 LLM、fast→deep 补跑判定。

集成侧（真实管道跑完 fast 并断言 LLM 调用数为 0）见 test_depth_integration.py。
"""
from pathlib import Path

import pytest

from app.models.tables import IndexDepth, Project
from app.services.ingest.pipeline import (
    MODE_AUTO,
    MODE_FULL,
    _summarize_all,
    build_index_plan,
)
from app.services.ingest.router_parser import ModuleMap, RouteModule
from app.services.ingest.summarizer import FAST_PREFIX
from tests.helpers.repos import commit_all, existing, make_repo


# ---------------- API 贯通 ----------------


@pytest.fixture
def started_jobs(monkeypatch, test_db):
    from app.models.tables import IndexJob

    calls: list[dict] = []

    async def fake_start(project_id, mode="auto", depth="deep"):
        calls.append({"mode": mode, "depth": depth})
        async with test_db() as session:
            job = IndexJob(project_id=project_id, kind=mode)
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    monkeypatch.setattr("app.api.projects.start_index_job", fake_start)
    return calls


async def _project(test_db, depth=IndexDepth.DEEP):
    async with test_db() as session:
        project = Project(
            name="p", git_url="https://example.com/x.git", index_depth=depth
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project.id


async def test_depth_defaults_to_deep(api_client, test_db, started_jobs):
    pid = await _project(test_db)
    resp = await api_client.post(f"/projects/{pid}/index")

    assert resp.status_code == 202
    assert started_jobs[0]["depth"] == IndexDepth.DEEP


async def test_depth_fast_accepted(api_client, test_db, started_jobs):
    """spec 场景: 以 depth=fast 触发索引。"""
    pid = await _project(test_db)
    resp = await api_client.post(f"/projects/{pid}/index?depth=fast")

    assert resp.status_code == 202
    assert started_jobs[0]["depth"] == IndexDepth.FAST


async def test_depth_combines_with_mode(api_client, test_db, started_jobs):
    """spec 场景: 补跑入口 depth=deep&mode=auto。"""
    pid = await _project(test_db, IndexDepth.FAST)
    resp = await api_client.post(f"/projects/{pid}/index?mode=auto&depth=deep")

    assert resp.status_code == 202
    assert started_jobs[0] == {"mode": MODE_AUTO, "depth": IndexDepth.DEEP}


async def test_invalid_depth_rejected(api_client, test_db, started_jobs):
    pid = await _project(test_db)
    resp = await api_client.post(f"/projects/{pid}/index?depth=turbo")

    assert resp.status_code == 422
    assert started_jobs == []


async def test_project_out_exposes_index_depth(api_client, test_db, started_jobs):
    pid = await _project(test_db, IndexDepth.FAST)
    body = (await api_client.get(f"/projects/{pid}")).json()
    assert body["index_depth"] == "fast"


# ---------------- fast→deep 补跑判定 ----------------


@pytest.fixture
def plan_stubs(monkeypatch):
    from app.core.config import settings

    state = {
        "files": existing(["a.py"]),
        "meta": {
            "embedding_model": settings.embedding_model,
            "embedding_dim": settings.embedding_dim,
        },
    }

    async def fake_files(pid):
        return dict(state["files"])

    async def fake_meta(pid):
        return dict(state["meta"])

    async def fake_chunks(pid, paths):
        return []

    monkeypatch.setattr("app.services.ingest.pipeline.load_file_metadata", fake_files)
    monkeypatch.setattr("app.services.ingest.pipeline.load_project_index_meta", fake_meta)
    monkeypatch.setattr("app.services.ingest.pipeline.load_chunk_metadata", fake_chunks)
    return state


@pytest.fixture
def unchanged_repo(tmp_path):
    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    sha = commit_all(repo, "init")
    return tmp_path, sha


async def _plan(repo_path, sha, depth, current_depth):
    return await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=repo_path,
        last_indexed_commit=sha, commit_sha=sha, walk_files=[Path("a.py")],
        depth=depth, current_depth=current_depth,
    )


async def test_fast_to_deep_forces_full_rebuild(plan_stubs, unchanged_repo):
    """spec 场景: fast 项目以 deep 触发时必须真正补跑（不能因无变更秒返）。

    走全量是因为新的 L2/L3 摘要要落到每个文件节点上，而增量只重写变更文件。
    """
    plan = await _plan(*unchanged_repo, IndexDepth.DEEP, IndexDepth.FAST)

    assert plan.mode == MODE_FULL
    assert plan.fallback_reason == "depth_upgraded_to_deep"
    assert plan.no_changes is False


async def test_deep_to_deep_no_changes_still_fast_path(plan_stubs, unchanged_repo):
    """同深度且无变更 → 保持秒返，不被升级判定误伤。"""
    plan = await _plan(*unchanged_repo, IndexDepth.DEEP, IndexDepth.DEEP)
    assert plan.no_changes is True


async def test_deep_to_fast_does_not_force_full(plan_stubs, unchanged_repo):
    """降级（deep→fast）没有补跑需求，不必强制全量。"""
    plan = await _plan(*unchanged_repo, IndexDepth.FAST, IndexDepth.DEEP)
    assert plan.no_changes is True


# ---------------- fast 摘要阶段零 LLM ----------------


class ExplodingSummarizer:
    """fast 模式下任何 LLM 调用都是缺陷——直接炸给测试看。"""

    async def summarize_file(self, *args, **kwargs):
        raise AssertionError("fast 模式不得调用 LLM 生成文件摘要")

    async def summarize_module(self, *args, **kwargs):
        raise AssertionError("fast 模式不得调用 LLM 生成模块摘要")

    async def summarize_project(self, *args, **kwargs):
        raise AssertionError("fast 模式不得调用 LLM 生成项目总览")


@pytest.fixture
def no_llm(monkeypatch):
    from app.services.ingest import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "summarizer", ExplodingSummarizer())


@pytest.fixture
def empty_cache(monkeypatch):
    async def fake_cache(project_id):
        return {}, {}

    monkeypatch.setattr("app.services.ingest.pipeline.load_summary_cache", fake_cache)


def make_files_and_chunks():
    from app.services.ingest.chunker import CodeChunk
    from app.services.ingest.graph_writer import FileInfo

    files = [
        FileInfo(path="src/service.ts", language="typescript", content_hash="h1",
                 modules=["api:orders"]),
        FileInfo(path="src/order.test.ts", language="typescript", content_hash="h2",
                 modules=["api:orders"]),
    ]
    chunks = [
        CodeChunk(file_path="src/service.ts", language="typescript", symbol="createOrder",
                  symbol_type="function", start_line=1, end_line=200,
                  code="function createOrder() {}", content_hash="c1"),
        CodeChunk(file_path="src/order.test.ts", language="typescript", symbol="itWorks",
                  symbol_type="function", start_line=1, end_line=50,
                  code="it('works')", content_hash="c2"),
    ]
    return files, chunks


async def test_fast_summarize_makes_no_llm_calls(no_llm, empty_cache):
    """spec 场景: fast 模式 summarize 阶段 LLM 调用数为 0。"""
    files, chunks = make_files_and_chunks()
    module_map = ModuleMap(
        modules=[RouteModule(name="orders", kind="api", route_prefix="/api/orders")]
    )
    stats: dict = {}

    module_summaries, l4, partial = await _summarize_all(
        "p", module_map, files, chunks, {}, {}, "", stats, depth=IndexDepth.FAST
    )

    assert partial is False
    assert stats["summaries_new"] == 0        # 零 LLM
    assert stats["summaries_rule"] >= 3       # 2 个 L2 + 1 个 L3 + L4
    # 测试文件走规则摘要，业务文件走 fast 占位
    assert "测试用例" in files[1].summary
    assert files[0].summary.startswith(FAST_PREFIX)
    assert module_summaries["api:orders"].startswith(FAST_PREFIX)
    assert "共 1 个功能模块" in l4


async def test_deep_uses_rules_before_llm(empty_cache, monkeypatch):
    """deep 模式下规则文件同样免 LLM，只有业务文件才调用。"""
    from app.services.ingest import pipeline as pipeline_module

    calls: list[str] = []

    class CountingSummarizer:
        async def summarize_file(self, path, imports, chunks, head):
            calls.append(path)
            return f"{path} 的职责摘要"

        async def summarize_module(self, *args, **kwargs):
            return "模块摘要"

        async def summarize_project(self, *args, **kwargs):
            return "项目总览"

    monkeypatch.setattr(pipeline_module, "summarizer", CountingSummarizer())
    files, chunks = make_files_and_chunks()
    module_map = ModuleMap(modules=[RouteModule(name="orders", kind="api", route_prefix="")])
    stats: dict = {}

    await _summarize_all(
        "p", module_map, files, chunks, {}, {}, "", stats, depth=IndexDepth.DEEP
    )

    assert calls == ["src/service.ts"]        # 测试文件没进 LLM
    assert stats["summaries_rule"] == 1
    assert stats["summaries_new"] == 3        # 1 个 L2 + 1 个 L3 + 1 个 L4
