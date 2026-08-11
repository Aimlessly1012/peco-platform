"""项目管理 API：CRUD + 索引触发 + 任务进度查询。"""
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.core.db import get_session
from app.graph.client import delete_project_graph
from app.models.tables import IndexJob, Project
from app.schemas import IndexJobOut, ProjectCreate, ProjectOut
from app.services.ingest.pipeline import start_index_job

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
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _get_project_or_404(project_id, session)
    job = await start_index_job(project_id)
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
