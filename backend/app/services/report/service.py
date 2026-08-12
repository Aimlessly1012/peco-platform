"""报告生成编排（B4 接入点）：读图 → 三件套 → upsert Postgres。

错误哲学：report 阶段任何失败都不阻塞索引成功，只把任务标 partial（spec）。
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.tables import IndexDepth, UnderstandingReport
from app.services.ingest.graph_writer import load_feature_cache, save_module_features
from app.services.report.builder import generate_doc, generate_sequences
from app.services.report.dataflow import build_dataflow
from app.services.report.features import generate_feature_map
from app.services.report.flows import generate_business_flows
from app.services.report.graph_reader import (
    read_graph_edges,
    read_module_anchors,
    read_module_edges,
    read_project_tree,
)
from app.services.report.llm import report_llm
from app.services.report.mindmap import build_mindmap

logger = logging.getLogger(__name__)


@dataclass
class ReportResult:
    doc_markdown: str = ""
    feature_map_markdown: str = ""
    business_flows: list[dict] = field(default_factory=list)
    mindmap_mermaid: str = ""
    dataflow_mermaid: str = ""
    sequences: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


async def build_report(
    project_id: str, llm=None, depth: str = IndexDepth.DEEP
) -> ReportResult:
    """读图生成报告四件。

    程序化两件（顶层导图、数据流图）零 LLM、必定成功；
    LLM 两件（需求文档、时序图）各自独立降级。fast 模式只产出程序化两件（M5 D7）。
    """
    llm = llm or report_llm
    tree = await read_project_tree(project_id)

    mindmap = build_mindmap(tree)
    module_edges = await read_module_edges(project_id)
    dataflow = build_dataflow(tree, module_edges)
    anchors = await read_module_anchors(project_id)

    if depth == IndexDepth.FAST:
        feature_map, _, feature_stats = await generate_feature_map(
            tree, anchors, llm, cache=None, fast=True
        )
        return ReportResult(
            doc_markdown="",
            feature_map_markdown=feature_map,
            mindmap_mermaid=mindmap,
            dataflow_mermaid=dataflow,
            sequences=[],
            stats={
                "report_modules": len(tree.modules),
                "report_depth": IndexDepth.FAST,
                "dataflow_edges": len(module_edges),
                "doc_fallback": False,
                "sequences_ok": 0,
                "sequences_fallback": 0,
                **feature_stats,
            },
        )

    edges = await read_graph_edges(project_id)
    feature_cache = await load_feature_cache(project_id)
    # 文档分批、功能点提取、业务流程图三条都是独立的 LLM 管线，并发跑（M6 B4/B5）
    (
        (doc, doc_fallback),
        (feature_map, cacheable, feature_stats),
        (business_flows, flow_stats),
    ) = await asyncio.gather(
        generate_doc(tree, llm),
        generate_feature_map(tree, anchors, llm, cache=feature_cache),
        generate_business_flows(tree, llm),
    )
    await save_module_features(project_id, cacheable)
    sequences, ok, fallback = await generate_sequences(tree, edges, llm)

    return ReportResult(
        doc_markdown=doc,
        feature_map_markdown=feature_map,
        business_flows=business_flows,
        mindmap_mermaid=mindmap,
        dataflow_mermaid=dataflow,
        sequences=sequences,
        stats={
            "report_modules": len(tree.modules),
            "report_depth": IndexDepth.DEEP,
            "dataflow_edges": len(module_edges),
            "doc_fallback": doc_fallback,
            "sequences_ok": ok,
            "sequences_fallback": fallback,
            **feature_stats,
            **flow_stats,
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
        report.feature_map_markdown = result.feature_map_markdown
        report.business_flows_json = result.business_flows
        report.mindmap_mermaid = result.mindmap_mermaid
        report.dataflow_mermaid = result.dataflow_mermaid
        report.sequences_json = result.sequences
        report.generated_at = datetime.now(timezone.utc)
        await session.commit()


async def generate_and_store_report(
    project_id: uuid.UUID, llm=None, depth: str = IndexDepth.DEEP
) -> dict:
    """pipeline report 阶段入口：返回 stats（含 partial 标记），自身不抛异常。"""
    try:
        result = await build_report(str(project_id), llm=llm, depth=depth)
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
