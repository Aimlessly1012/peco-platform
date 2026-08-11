"""报告生成编排（B4 接入点）：读图 → 三件套 → upsert Postgres。

错误哲学：report 阶段任何失败都不阻塞索引成功，只把任务标 partial（spec）。
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.tables import UnderstandingReport
from app.services.report.builder import generate_doc, generate_sequences
from app.services.report.graph_reader import read_graph_edges, read_project_tree
from app.services.report.llm import report_llm
from app.services.report.mindmap import build_mindmap

logger = logging.getLogger(__name__)


@dataclass
class ReportResult:
    doc_markdown: str = ""
    mindmap_mermaid: str = ""
    sequences: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


async def build_report(project_id: str, llm=None) -> ReportResult:
    """读图生成三件套。思维导图程序化必成；文档与时序图各自独立降级。"""
    llm = llm or report_llm
    tree = await read_project_tree(project_id)
    edges = await read_graph_edges(project_id)

    mindmap = build_mindmap(tree)
    doc, doc_fallback = await generate_doc(tree, llm)
    sequences, ok, fallback = await generate_sequences(tree, edges, llm)

    return ReportResult(
        doc_markdown=doc,
        mindmap_mermaid=mindmap,
        sequences=sequences,
        stats={
            "report_modules": len(tree.modules),
            "doc_fallback": doc_fallback,
            "sequences_ok": ok,
            "sequences_fallback": fallback,
        },
    )


async def upsert_report(project_id: uuid.UUID, result: ReportResult) -> None:
    """一项目一行，重索引覆盖写（设计 D3）。"""
    async with SessionLocal() as session:
        report = await session.scalar(
            select(UnderstandingReport).where(
                UnderstandingReport.project_id == project_id
            )
        )
        if report is None:
            report = UnderstandingReport(project_id=project_id)
            session.add(report)
        report.doc_markdown = result.doc_markdown
        report.mindmap_mermaid = result.mindmap_mermaid
        report.sequences_json = result.sequences
        report.generated_at = datetime.now(timezone.utc)
        await session.commit()


async def generate_and_store_report(project_id: uuid.UUID, llm=None) -> dict:
    """pipeline report 阶段入口：返回 stats（含 partial 标记），自身不抛异常。"""
    try:
        result = await build_report(str(project_id), llm=llm)
        await upsert_report(project_id, result)
        stats = dict(result.stats)
        stats["report_ok"] = True
        # 文档降级或有时序图降级 → 任务标 partial（但索引仍算成功）
        stats["report_partial"] = bool(
            stats.get("doc_fallback") or stats.get("sequences_fallback")
        )
        return stats
    except Exception as e:  # noqa: BLE001 — report 失败不得阻塞索引成功
        logger.exception("理解报告生成失败（不阻塞索引）")
        return {
            "report_ok": False,
            "report_partial": True,
            "report_error": f"{type(e).__name__}: {e}",
            "sequences_ok": 0,
            "sequences_fallback": 0,
        }


async def get_report(project_id: uuid.UUID) -> UnderstandingReport | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(UnderstandingReport).where(
                UnderstandingReport.project_id == project_id
            )
        )
