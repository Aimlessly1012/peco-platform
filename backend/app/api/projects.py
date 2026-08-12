"""项目管理 API：CRUD + 索引触发 + 任务进度查询。"""
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
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
    start_index_job,
)
from app.services.report.graph_reader import read_project_tree

router = APIRouter(prefix="/projects", tags=["projects"])


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
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
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
    job = await start_index_job(project_id, mode, depth)
    if job is None:
        raise HTTPException(409, "该项目已有索引任务在运行")
    return job


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
        mindmap_mermaid=report.mindmap_mermaid,
        dataflow_mermaid=report.dataflow_mermaid or "",
        sequences=report.sequences_json or [],
        # 没有文档正文即 fast 产物（程序化两件）——前端据此显示「生成深度理解」
        depth=IndexDepth.FAST if not report.doc_markdown else IndexDepth.DEEP,
        generated_at=report.generated_at,
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
