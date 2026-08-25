"""项目管理 API：CRUD + 索引触发 + 任务进度查询。"""
import asyncio
import logging
import shutil
import uuid

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.core.db import get_session
from app.graph.client import delete_project_graph
from app.models.tables import IndexDepth, IndexJob, Project, UnderstandingReport
from app.schemas import (
    IndexJobOut,
    ModuleMapOut,
    ProjectCreate,
    ProjectOut,
    ReportOut,
)
from app.services.ingest.pipeline import (
    MODE_AUTO,
    VALID_DEPTHS,
    VALID_MODES,
    TaskQueueUnavailable,
    start_index_job,
)
from app.services.ingest.progress_broker import (
    is_terminal,
    job_event,
    progress_broker,
)
from app.services.auth.deps import require_admin, require_user
from app.services.report.graph_reader import read_project_tree
from app.services.storage.minio_client import put_bytes

logger = logging.getLogger(__name__)

# M8：整组业务路由要求登录态。/auth/*、/health、/mcp 不在此列（见 deps.py 注释）
router = APIRouter(
    prefix="/projects", tags=["projects"], dependencies=[Depends(require_user)]
)


async def _get_project_or_404(project_id: uuid.UUID, session: AsyncSession) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "项目不存在")
    return project


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreate, session: AsyncSession = Depends(get_session)
):
    project = Project(
        name=payload.name,
        git_url=payload.git_url,
        git_token_encrypted=encrypt_token(payload.git_token) if payload.git_token else None,
        default_branch=payload.default_branch,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Project).order_by(desc(Project.created_at)))
    return list(result)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return await _get_project_or_404(project_id, session)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    admin: Project = Depends(require_admin),   # M8：删项目是不可逆操作，仅 admin
):
    """级联删除：Postgres 记录（FK cascade）+ Neo4j 子图 + 本地仓库副本。"""
    project = await _get_project_or_404(project_id, session)
    await delete_project_graph(str(project_id))
    repo_dir = settings.repos_dir / str(project_id)
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
    await session.delete(project)
    await session.commit()


@router.post("/{project_id}/index", response_model=IndexJobOut, status_code=202)
async def trigger_index(
    project_id: uuid.UUID,
    mode: str = Query(
        MODE_AUTO,
        description="auto=有基准 commit 时增量（默认），full=强制全量重建",
    ),
    depth: str = Query(
        IndexDepth.DEEP,
        description="deep=完整理解（默认），fast=零 LLM 快速录入",
    ),
    session: AsyncSession = Depends(get_session),
):
    """M4：默认 auto（可增量）。M5：depth 控制理解深度，实际路径写回任务 kind 与项目 index_depth。"""
    if mode not in VALID_MODES:
        raise HTTPException(422, f"mode 仅支持 {' / '.join(VALID_MODES)}")
    if depth not in VALID_DEPTHS:
        raise HTTPException(422, f"depth 仅支持 {' / '.join(VALID_DEPTHS)}")
    await _get_project_or_404(project_id, session)
    try:
        job = await start_index_job(project_id, mode, depth)
    except TaskQueueUnavailable:
        # M13：任务没进队列就没人会执行它，不能返回 202 让前端空等进度
        raise HTTPException(503, "任务队列不可用，请稍后重试") from None
    if job is None:
        raise HTTPException(409, "该项目已有索引任务在运行")
    return job


@router.get("/{project_id}/progress")
async def progress_stream(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """索引进度 SSE（M9 B2）：首连推快照 → 增量 → 终态关流。

    没有运行中的任务就直接关流（不吊着连接）——前端触发索引后再连。
    """
    await _get_project_or_404(project_id, session)
    latest = await session.scalar(
        select(IndexJob)
        .where(IndexJob.project_id == project_id)
        .order_by(desc(IndexJob.started_at))
        .limit(1)
    )
    snapshot = job_event(latest) if latest is not None else {"status": "idle"}

    async def event_stream():
        # 先订阅再推快照：反过来的话，两步之间产生的事件会丢
        with progress_broker.subscribe(str(project_id)) as queue:
            yield {"event": "progress", "data": json.dumps(snapshot)}
            if latest is None or is_terminal(snapshot):
                return                      # 无任务 / 已终态：推完就走
            while True:
                event = await queue.get()
                yield {"event": "progress", "data": json.dumps(event)}
                if is_terminal(event):
                    return

    # sep="\n" 与 15s ping 沿用 M6 事故修复后的既有配置，别改
    return EventSourceResponse(event_stream(), sep="\n", ping=15)


@router.get("/{project_id}/jobs", response_model=list[IndexJobOut])
async def list_jobs(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _get_project_or_404(project_id, session)
    result = await session.scalars(
        select(IndexJob)
        .where(IndexJob.project_id == project_id)
        .order_by(desc(IndexJob.started_at))
        .limit(20)
    )
    return list(result)


@router.get("/{project_id}/report", response_model=ReportOut)
async def get_report(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """理解报告三件套。无报告 = 索引早于 M3 或未完成（spec: 404 附提示）。"""
    await _get_project_or_404(project_id, session)
    report = await session.scalar(
        select(UnderstandingReport).where(UnderstandingReport.project_id == project_id)
    )
    if report is None:
        raise HTTPException(404, "该项目还没有理解报告，请重新索引以生成报告")
    return ReportOut(
        project_id=report.project_id,
        doc_markdown=report.doc_markdown,
        feature_map_markdown=report.feature_map_markdown or "",
        business_flows=report.business_flows_json or [],
        page_map_markdown=report.page_map_markdown or "",
        mindmap_mermaid=report.mindmap_mermaid,
        dataflow_mermaid=report.dataflow_mermaid or "",
        sequences=report.sequences_json or [],
        # 没有文档正文即 fast 产物（程序化两件）——前端据此显示「生成深度理解」
        depth=IndexDepth.FAST if not report.doc_markdown else IndexDepth.DEEP,
        generated_at=report.generated_at,
    )


@router.get("/{project_id}/report/export")
async def export_report(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """理解报告导出为 Markdown 文件（M13 4.2）。

    正文 = 文档正文 + 需求功能导图。同时写一份进 MinIO（reports/{project_id}.md）
    留档，但对象存储是非关键路径：上传失败只记 warning，文件照常返回给用户。
    """
    await _get_project_or_404(project_id, session)
    report = await session.scalar(
        select(UnderstandingReport).where(UnderstandingReport.project_id == project_id)
    )
    if report is None:
        raise HTTPException(404, "该项目还没有理解报告，请重新索引以生成报告")

    content = f"{report.doc_markdown or ''}\n\n{report.feature_map_markdown or ''}"
    payload = content.encode("utf-8")
    try:
        await asyncio.to_thread(
            put_bytes, f"reports/{project_id}.md", payload, "text/markdown"
        )
    except Exception as e:  # noqa: BLE001 — 留档失败不该让用户下不到文件
        logger.warning("报告导出件上传 MinIO 失败（不影响下载）：%s", e)

    return Response(
        content=payload,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="report-{project_id}.md"'
        },
    )


@router.get("/{project_id}/modules", response_model=ModuleMapOut)
async def get_modules(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """功能地图：实时读 Neo4j（未索引的项目返回空模块列表，由前端引导索引）。"""
    project = await _get_project_or_404(project_id, session)
    tree = await read_project_tree(str(project_id))
    return ModuleMapOut(
        project_id=project_id,
        project_name=tree.name or project.name,
        project_summary=tree.summary,
        modules=[
            {
                "key": m.key,
                "name": m.name,
                "kind": m.kind,
                "route_prefix": m.route_prefix,
                "summary": m.summary,
                "files": [
                    {"path": f.path, "language": f.language, "summary": f.summary}
                    for f in m.files
                ],
            }
            for m in tree.modules
        ],
    )


@router.get("/{project_id}/jobs/latest", response_model=IndexJobOut)
async def latest_job(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _get_project_or_404(project_id, session)
    job = await session.scalar(
        select(IndexJob)
        .where(IndexJob.project_id == project_id)
        .order_by(desc(IndexJob.started_at))
        .limit(1)
    )
    if job is None:
        raise HTTPException(404, "该项目还没有索引任务")
    return job
