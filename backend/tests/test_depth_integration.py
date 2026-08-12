"""深度模式集成测试（M5 B8，需要 Neo4j）：fast 零 LLM 与 fast→deep 补跑。

LLM 调用一律经 summarizer._complete / report_llm._complete，这里对这两处计数，
所以"零 LLM"是真的零，而不是"我觉得没调"。
"""
import uuid

import pytest

from app.graph.client import close_driver, delete_project_graph, ensure_vector_index, get_driver
from app.models.tables import IndexDepth, IndexJob, Project, UnderstandingReport
from app.services.ingest.pipeline import MODE_AUTO, MODE_FULL, run_index_job
from app.services.ingest.summarizer import summarizer
from app.services.report.llm import report_llm
from sqlalchemy import select
from tests.test_incremental_integration import make_source_repo

pytestmark = pytest.mark.integration


@pytest.fixture
def llm_counter(monkeypatch):
    """统计真实发生的 LLM 调用次数（摘要与报告两条路径）。"""
    counts = {"summary": 0, "report": 0}

    async def count_summary(self, prompt):
        counts["summary"] += 1
        return "该文件负责示例业务逻辑"

    async def count_report(self, prompt, max_tokens=1000):
        counts["report"] += 1
        if "sequenceDiagram" in prompt:
            return (
                "sequenceDiagram\n    participant U as 用户\n"
                "    participant S as 服务\n    U->>S: 请求\n    S-->>U: 响应"
            )
        return "### 示例章节\n**业务目标**：示例"

    monkeypatch.setattr(type(summarizer), "_complete", count_summary)
    monkeypatch.setattr(type(report_llm), "_complete", count_report)
    return counts


@pytest.fixture
async def depth_env(tmp_path, test_db, fake_embedder, monkeypatch):
    from app.core.config import settings

    await ensure_vector_index()
    monkeypatch.setattr(settings, "repos_dir", tmp_path / "repos")

    source = tmp_path / "source"
    make_source_repo(source)
    created: list[uuid.UUID] = []

    async def new_project() -> uuid.UUID:
        async with test_db() as session:
            project = Project(name=f"depth-{uuid.uuid4().hex[:6]}", git_url=str(source))
            session.add(project)
            await session.commit()
            await session.refresh(project)
            created.append(project.id)
            return project.id

    async def run(project_id: uuid.UUID, mode: str, depth: str) -> IndexJob:
        async with test_db() as session:
            job = IndexJob(project_id=project_id, kind=mode)
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id
        await run_index_job(job_id, project_id, mode, depth)
        async with test_db() as session:
            return await session.get(IndexJob, job_id)

    yield {"new_project": new_project, "run": run, "db": test_db}

    for pid in created:
        await delete_project_graph(str(pid))
    await close_driver()


async def _report(test_db, pid) -> UnderstandingReport | None:
    async with test_db() as session:
        return await session.scalar(
            select(UnderstandingReport).where(UnderstandingReport.project_id == pid)
        )


async def _count_nodes(project_id: str, label: str) -> int:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"MATCH (n:{label} {{project_id: $pid}}) RETURN count(n) AS n",
            pid=project_id,
        )
        return (await result.single())["n"]


async def test_fast_index_makes_zero_llm_calls(depth_env, llm_counter):
    """spec 场景: fast 索引任务成功且 summarize/report 阶段 LLM 调用数为 0。"""
    pid = await depth_env["new_project"]()
    job = await depth_env["run"](pid, MODE_FULL, IndexDepth.FAST)

    assert job.status == "succeeded", job.error_text
    assert llm_counter == {"summary": 0, "report": 0}
    assert job.stats_json["depth"] == IndexDepth.FAST
    assert job.stats_json["summaries_new"] == 0
    assert job.stats_json["summaries_rule"] > 0


async def test_fast_index_keeps_graph_and_retrieval_usable(depth_env, llm_counter):
    """fast 不打折的部分：图结构、模块划分与代码块嵌入。"""
    pid = await depth_env["new_project"]()
    await depth_env["run"](pid, MODE_FULL, IndexDepth.FAST)

    assert await _count_nodes(str(pid), "Chunk") > 0
    assert await _count_nodes(str(pid), "Module") > 0
    assert await _count_nodes(str(pid), "File") > 0

    from app.services.retrieval.service import search_layered

    results = await search_layered(str(pid), "创建订单的接口", "local", top_k=5)
    assert results, "fast 模式的代码检索必须可用"


async def test_fast_report_has_only_programmatic_artifacts(depth_env, llm_counter):
    pid = await depth_env["new_project"]()
    await depth_env["run"](pid, MODE_FULL, IndexDepth.FAST)

    report = await _report(depth_env["db"], pid)
    assert report.mindmap_mermaid.startswith("mindmap")
    assert report.dataflow_mermaid.startswith("flowchart LR")
    assert report.doc_markdown == ""
    assert report.sequences_json == []


async def test_project_records_index_depth(depth_env, llm_counter):
    pid = await depth_env["new_project"]()
    await depth_env["run"](pid, MODE_FULL, IndexDepth.FAST)

    async with depth_env["db"]() as session:
        assert (await session.get(Project, pid)).index_depth == IndexDepth.FAST


async def test_fast_to_deep_only_pays_the_difference(depth_env, llm_counter):
    """spec 场景: fast 项目无代码变更时以 deep 触发 → 嵌入全缓存，只补 LLM 摘要与报告。"""
    pid = await depth_env["new_project"]()
    await depth_env["run"](pid, MODE_FULL, IndexDepth.FAST)
    assert llm_counter == {"summary": 0, "report": 0}

    job = await depth_env["run"](pid, MODE_AUTO, IndexDepth.DEEP)

    assert job.status == "succeeded", job.error_text
    assert job.stats_json["depth"] == IndexDepth.DEEP
    assert job.stats_json["fallback_full_reason"] == "depth_upgraded_to_deep"
    # 嵌入以复用为主：embed_key 含嵌入文本、文本含文件摘要（M2 D5——摘要变则向量重算），
    # 所以只有"fast 占位摘要 → LLM 摘要"的那些文件会重嵌，规则摘要文件原样复用
    assert job.stats_json["embedded_cached"] > job.stats_json["embedded_new"]
    # 但确实补了 LLM 摘要与报告
    assert llm_counter["summary"] > 0
    assert llm_counter["report"] > 0
    assert job.stats_json["summaries_new"] > 0

    report = await _report(depth_env["db"], pid)
    assert report.doc_markdown.startswith("#")
    assert "### 示例章节" in report.doc_markdown
    assert report.dataflow_mermaid.startswith("flowchart LR")

    async with depth_env["db"]() as session:
        assert (await session.get(Project, pid)).index_depth == IndexDepth.DEEP


async def test_deep_reindex_reuses_summary_cache(depth_env, llm_counter):
    """deep 之后再 deep（无变更）→ 摘要缓存命中，不再重复付费。"""
    pid = await depth_env["new_project"]()
    await depth_env["run"](pid, MODE_FULL, IndexDepth.DEEP)
    first_round = llm_counter["summary"]
    assert first_round > 0

    job = await depth_env["run"](pid, MODE_FULL, IndexDepth.DEEP)

    assert job.status == "succeeded", job.error_text
    assert job.stats_json["summaries_cached"] > 0
    # L2/L3 全缓存命中；L4 每次重算，所以只多这一次
    assert llm_counter["summary"] - first_round <= 1
