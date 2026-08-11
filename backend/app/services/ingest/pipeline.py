"""索引管道编排：clone → parse → embed → graph（M1 全量重建语义）。

进度区间：clone 0-10, parse 10-30, embed 30-80, graph 80-100。
每阶段实时落库；失败置 job failed + project failed；成功置 ready。
"""
import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import decrypt_token
from app.core.db import SessionLocal
from app.graph.client import delete_project_graph
from app.models.tables import IndexJob, JobStage, JobStatus, Project, ProjectStatus
from app.services.ingest.chunker import ChunkError, CodeChunk, chunk_file
from app.services.ingest.embedder import embedder
from app.services.ingest.git_ops import GitPullError, pull_repo
from app.services.ingest.graph_writer import (
    FileInfo,
    load_embedding_cache,
    write_project_graph,
)
from app.services.ingest.walker import LANGUAGE_BY_EXT, walk_repo

logger = logging.getLogger(__name__)


def build_embed_text(chunk: CodeChunk) -> str:
    """M1 版上下文头（M2 将补充模块归属与文件职责摘要）。"""
    return (
        f"[文件: {chunk.file_path} | 符号: {chunk.symbol} ({chunk.symbol_type})]\n"
        f"{chunk.code}"
    )


async def _update_job(job_id: uuid.UUID, **values) -> None:
    async with SessionLocal() as session:
        job = await session.get(IndexJob, job_id)
        for k, v in values.items():
            setattr(job, k, v)
        await session.commit()


async def _finish(
    job_id: uuid.UUID, project_id: uuid.UUID,
    *, error: str | None = None, commit_sha: str | None = None,
) -> None:
    from datetime import datetime, timezone

    async with SessionLocal() as session:
        job = await session.get(IndexJob, job_id)
        project = await session.get(Project, project_id)
        job.finished_at = datetime.now(timezone.utc)
        if error is None:
            job.status = JobStatus.SUCCEEDED
            job.progress = 100
            project.status = ProjectStatus.READY
            if commit_sha:
                project.last_indexed_commit = commit_sha
        else:
            job.status = JobStatus.FAILED
            job.error_text = error
            project.status = ProjectStatus.FAILED
        await session.commit()


def _parse_all(repo_dir: Path, rel_files: list[Path]) -> tuple[list[FileInfo], list[CodeChunk], int]:
    """解析全部文件（线程池内运行）；单文件失败跳过（spec: 不中断）。"""
    files: list[FileInfo] = []
    chunks: list[CodeChunk] = []
    parse_failed = 0
    for rel in rel_files:
        try:
            file_chunks = chunk_file(repo_dir, rel)
        except ChunkError as e:
            logger.warning("跳过文件 %s: %s", rel, e)
            parse_failed += 1
            continue
        raw = (repo_dir / rel).read_bytes()
        files.append(
            FileInfo(
                path=str(rel),
                language=LANGUAGE_BY_EXT[rel.suffix.lower()],
                content_hash=hashlib.sha256(raw).hexdigest()[:16],
            )
        )
        chunks.extend(file_chunks)
    return files, chunks, parse_failed


async def run_index_job(job_id: uuid.UUID, project_id: uuid.UUID) -> None:
    pid = str(project_id)
    try:
        async with SessionLocal() as session:
            project = await session.get(Project, project_id)
            git_url = project.git_url
            name = project.name
            branch = project.default_branch
            token = (
                decrypt_token(project.git_token_encrypted)
                if project.git_token_encrypted
                else None
            )

        # ---- clone (0-10) ----
        await _update_job(job_id, stage=JobStage.CLONE, progress=0)
        repo_dir = settings.repos_dir / pid
        commit_sha = await asyncio.to_thread(pull_repo, git_url, repo_dir, token, branch)
        await _update_job(job_id, progress=10)

        # ---- parse (10-30) ----
        await _update_job(job_id, stage=JobStage.PARSE)
        walk = await asyncio.to_thread(walk_repo, repo_dir)
        files, chunks, parse_failed = await asyncio.to_thread(
            _parse_all, repo_dir, walk.files
        )
        stats = {
            "files_parsed": len(files),
            "files_skipped": walk.skipped + parse_failed,
            "chunks": len(chunks),
        }
        await _update_job(job_id, progress=30, stats_json=stats)

        # ---- embed (30-80)：先读旧向量缓存，再删旧子图（全量重建仍复用缓存，D5）----
        await _update_job(job_id, stage=JobStage.EMBED)
        cache = await load_embedding_cache(pid)
        await delete_project_graph(pid)

        context_texts = {c.content_hash: build_embed_text(c) for c in chunks}
        embeddings: dict[str, list[float]] = {}
        to_embed: list[CodeChunk] = []
        seen_hashes: set[str] = set()
        for c in chunks:
            if c.content_hash in seen_hashes:
                continue
            seen_hashes.add(c.content_hash)
            if c.content_hash in cache:
                embeddings[c.content_hash] = cache[c.content_hash]
            else:
                to_embed.append(c)

        if to_embed:
            vectors = await embedder.embed_texts(
                [context_texts[c.content_hash] for c in to_embed]
            )
            for c, v in zip(to_embed, vectors):
                embeddings[c.content_hash] = v

        stats.update(
            {"embedded_new": len(to_embed), "embedded_cached": len(seen_hashes) - len(to_embed)}
        )
        await _update_job(job_id, progress=80, stats_json=stats)

        # ---- graph (80-100) ----
        await _update_job(job_id, stage=JobStage.GRAPH)
        await write_project_graph(
            pid, name, git_url, files, chunks, context_texts, embeddings
        )
        await _finish(job_id, project_id, commit_sha=commit_sha)
        logger.info("项目 %s 索引完成: %s", name, stats)

    except GitPullError as e:
        await _finish(job_id, project_id, error=str(e))
    except Exception as e:  # noqa: BLE001 — 管道兜底，任何失败都要落库
        logger.exception("索引任务失败")
        await _finish(job_id, project_id, error=f"索引失败：{type(e).__name__}: {e}")


async def start_index_job(project_id: uuid.UUID) -> IndexJob | None:
    """创建任务并启动后台协程；已有 running 任务返回 None（API 层转 409）。"""
    async with SessionLocal() as session:
        running = await session.scalar(
            select(IndexJob).where(
                IndexJob.project_id == project_id,
                IndexJob.status == JobStatus.RUNNING,
            )
        )
        if running:
            return None
        job = IndexJob(project_id=project_id, kind="full")
        session.add(job)
        project = await session.get(Project, project_id)
        project.status = ProjectStatus.INDEXING
        await session.commit()
        await session.refresh(job)

    asyncio.create_task(run_index_job(job.id, project_id))
    return job
