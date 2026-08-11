"""索引管道编排（M2 五阶段）：clone → parse → summarize → embed → graph。

进度区间：clone 0-10, parse 10-25, summarize 25-55, embed 55-85, graph 85-100。
嵌入缓存键 = 嵌入文本 hash（embed_key）而非代码 hash——摘要/归属变化时向量随之重算。
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
from app.services.ingest.api_matcher import extract_api_edges
from app.services.ingest.chunker import ChunkError, CodeChunk, chunk_file
from app.services.ingest.deps_extractor import extract_imports
from app.services.ingest.embedder import embedder
from app.services.ingest.git_ops import GitPullError, pull_repo
from app.services.ingest.graph_writer import (
    FileInfo,
    ModuleInfo,
    load_embedding_cache,
    load_summary_cache,
    write_project_graph,
)
from app.services.ingest.module_mapper import (
    assign_files,
    ensure_shared_module,
    module_key,
)
from app.services.ingest.router_parser import ModuleMap, parse_routes
from app.services.ingest.summarizer import fallback_summary, module_agg_hash, summarizer
from app.services.ingest.walker import LANGUAGE_BY_EXT, walk_repo

logger = logging.getLogger(__name__)


def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def build_embed_text(
    chunk: CodeChunk, project_name: str, modules: list[str],
    route_prefix: str, file_summary: str,
) -> str:
    """M2 上下文增强嵌入头（spec: 上下文增强嵌入）。modules 为 "kind:name" 键，显示名部分。"""
    module_part = (
        ", ".join(m.split(":", 1)[-1] for m in modules) if modules else "shared"
    )
    return (
        f"[项目: {project_name} | 模块: {module_part}"
        f"{f' ({route_prefix})' if route_prefix else ''}"
        f" | 文件: {chunk.file_path} | 符号: {chunk.symbol} ({chunk.symbol_type})]\n"
        f"[文件职责: {file_summary[:120] if file_summary else '未知'}]\n"
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


def _parse_all(
    repo_dir: Path, rel_files: list[Path]
) -> tuple[list[FileInfo], list[CodeChunk], dict[str, set[str]], dict[str, str], int]:
    """解析全部文件（线程池内）：分块 + IMPORTS + 文件头。单文件失败跳过。"""
    all_rel = {str(f) for f in rel_files}
    files: list[FileInfo] = []
    chunks: list[CodeChunk] = []
    imports: dict[str, set[str]] = {}
    heads: dict[str, str] = {}
    parse_failed = 0
    for rel in rel_files:
        try:
            file_chunks = chunk_file(repo_dir, rel)
        except ChunkError as e:
            logger.warning("跳过文件 %s: %s", rel, e)
            parse_failed += 1
            continue
        rel_str = str(rel)
        raw = (repo_dir / rel).read_bytes()
        files.append(
            FileInfo(
                path=rel_str,
                language=LANGUAGE_BY_EXT[rel.suffix.lower()],
                content_hash=hashlib.sha256(raw).hexdigest()[:16],
            )
        )
        heads[rel_str] = raw[:800].decode("utf-8", errors="ignore")
        imports[rel_str] = extract_imports(repo_dir, rel, all_rel)
        chunks.extend(file_chunks)
    return files, chunks, imports, heads, parse_failed


def _collect_repo_files(repo_dir: Path, files: list[FileInfo]) -> dict[str, str]:
    """路由探测所需的源文本 + 各级 package.json。"""
    repo_files: dict[str, str] = {}
    for f in files:
        try:
            repo_files[f.path] = (repo_dir / f.path).read_text(
                encoding="utf-8", errors="ignore"
            )
        except OSError:
            continue
    for pkg in repo_dir.rglob("package.json"):
        rel = pkg.relative_to(repo_dir)
        if "node_modules" in rel.parts:
            continue
        try:
            repo_files[str(rel)] = pkg.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return repo_files


def _read_readme(repo_dir: Path) -> str:
    for name in ("README.md", "readme.md", "README.rst", "README.txt"):
        p = repo_dir / name
        if p.exists():
            try:
                return p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return ""
    return ""


async def _summarize_all(
    project_id: str,
    module_map: ModuleMap,
    files: list[FileInfo],
    chunks: list[CodeChunk],
    imports: dict[str, set[str]],
    heads: dict[str, str],
    readme: str,
    stats: dict,
) -> tuple[dict[str, str], str, bool]:
    """生成 L2/L3/L4；返回 (module_name→L3, L4, partial)。L2 直接写入 files[].summary。"""
    file_cache, module_cache = await load_summary_cache(project_id)
    chunks_by_file: dict[str, list[CodeChunk]] = {}
    for c in chunks:
        chunks_by_file.setdefault(c.file_path, []).append(c)

    partial = False
    new_calls = 0
    cached_hits = 0

    async def l2_for(f: FileInfo) -> None:
        nonlocal new_calls, cached_hits, partial
        if f.content_hash in file_cache:
            f.summary = file_cache[f.content_hash]
            cached_hits += 1
            return
        result = await summarizer.summarize_file(
            f.path, imports.get(f.path, set()),
            chunks_by_file.get(f.path, []), heads.get(f.path, ""),
        )
        new_calls += 1
        if result is None:
            f.summary = fallback_summary(f.path, chunks_by_file.get(f.path, []))
            partial = True
        else:
            f.summary = result

    await asyncio.gather(*(l2_for(f) for f in files))

    # L3：模块摘要（缓存键 = 模块内文件 hash 聚合；字典键 = "kind:name" 唯一键）
    files_by_path = {f.path: f for f in files}
    module_summaries: dict[str, str] = {}
    module_hashes: dict[str, str] = {}
    for mod in module_map.modules:
        key = module_key(mod)
        member_files = [f for f in files if key in f.modules]
        agg = module_agg_hash([f.content_hash for f in member_files]) if member_files else ""
        module_hashes[key] = agg
        if agg and agg in module_cache:
            module_summaries[key] = module_cache[agg]
            cached_hits += 1
            continue
        file_summaries = {f.path: f.summary for f in member_files[:30]}
        result = await summarizer.summarize_module(
            mod.name, mod.kind, mod.route_prefix,
            [e for e in mod.entry_files if e in files_by_path][:15],
            file_summaries,
        )
        new_calls += 1
        if result is None:
            module_summaries[key] = (
                f"（摘要生成失败）模块 {mod.name}，含 {len(member_files)} 个文件"
            )
            partial = True
        else:
            module_summaries[key] = result

    # L4：项目总览（每次重算）
    l4 = await summarizer.summarize_project(readme, module_map, module_summaries)
    new_calls += 1
    if l4 is None:
        l4 = "（项目总览生成失败）模块列表：" + ", ".join(module_summaries)
        partial = True

    stats["summaries_new"] = new_calls
    stats["summaries_cached"] = cached_hits
    stats["_module_hashes"] = module_hashes
    return module_summaries, l4, partial


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

        # ---- parse (10-25)：分块 + IMPORTS + 路由 + 归属 ----
        await _update_job(job_id, stage=JobStage.PARSE)
        walk = await asyncio.to_thread(walk_repo, repo_dir)
        files, chunks, imports, heads, parse_failed = await asyncio.to_thread(
            _parse_all, repo_dir, walk.files
        )
        repo_files = await asyncio.to_thread(_collect_repo_files, repo_dir, files)
        file_paths = [f.path for f in files]
        module_map = parse_routes(file_paths, repo_files)
        assignment = assign_files(file_paths, module_map, imports)
        ensure_shared_module(module_map, assignment)
        for f in files:
            f.modules = assignment.get(f.path, ["shared"])
            f.imports = sorted(imports.get(f.path, set()))

        chunks_by_key = {(c.file_path, c.symbol): c for c in chunks}
        frontend_chunks = [c for c in chunks if c.language != "python"]
        api_edges, api_warnings = extract_api_edges(
            frontend_chunks, module_map.backend_routes, chunks_by_key
        )
        stats = {
            "files_parsed": len(files),
            "files_skipped": walk.skipped + parse_failed,
            "chunks": len(chunks),
            "modules": len(module_map.modules),
            "api_edges": len(api_edges),
            "api_warnings": api_warnings,
            "router_fallback": module_map.fallback,
        }
        await _update_job(job_id, progress=25, stats_json=stats)

        # ---- summarize (25-55) ----
        await _update_job(job_id, stage=JobStage.SUMMARIZE)
        readme = await asyncio.to_thread(_read_readme, repo_dir)
        module_summaries, project_summary, partial = await _summarize_all(
            pid, module_map, files, chunks, imports, heads, readme, stats
        )
        module_hashes = stats.pop("_module_hashes", {})
        public_stats = {k: v for k, v in stats.items()}
        await _update_job(job_id, progress=55, stats_json=public_stats)

        # ---- embed (55-85)：缓存键 = 嵌入文本 hash ----
        await _update_job(job_id, stage=JobStage.EMBED)
        cache = await load_embedding_cache(pid)
        await delete_project_graph(pid)

        files_by_path = {f.path: f for f in files}
        embed_texts: dict[str, str] = {}
        embed_keys: dict[str, str] = {}  # content_hash → embed_key
        for c in chunks:
            f = files_by_path.get(c.file_path)
            text = build_embed_text(
                c, name,
                f.modules if f else ["shared:shared"],
                next(
                    (m.route_prefix for m in module_map.modules
                     if f and module_key(m) in f.modules and m.route_prefix), "",
                ),
                f.summary if f else "",
            )
            embed_texts[c.content_hash] = text
            embed_keys[c.content_hash] = _hash16(text)

        embeddings: dict[str, list[float]] = {}
        to_embed: list[str] = []  # content_hash 列表
        seen: set[str] = set()
        for c in chunks:
            if c.content_hash in seen:
                continue
            seen.add(c.content_hash)
            key = embed_keys[c.content_hash]
            if key in cache:
                embeddings[c.content_hash] = cache[key]
            else:
                to_embed.append(c.content_hash)
        if to_embed:
            vectors = await embedder.embed_texts([embed_texts[h] for h in to_embed])
            for h, v in zip(to_embed, vectors):
                embeddings[h] = v

        # File / Module 摘要嵌入（量小，不缓存）
        summary_texts = [f.summary or f.path for f in files]
        file_vectors = await embedder.embed_texts(summary_texts) if files else []
        for f, v in zip(files, file_vectors):
            f.summary_embedding = v

        modules_info = [
            ModuleInfo(
                name=m.name, key=module_key(m), kind=m.kind, route_prefix=m.route_prefix,
                summary=module_summaries.get(module_key(m), ""),
                agg_hash=module_hashes.get(module_key(m), ""),
            )
            for m in module_map.modules
        ]
        module_vectors = (
            await embedder.embed_texts([m.summary or m.name for m in modules_info])
            if modules_info else []
        )
        for m, v in zip(modules_info, module_vectors):
            m.summary_embedding = v

        stats["embedded_new"] = len(to_embed)
        stats["embedded_cached"] = len(seen) - len(to_embed)
        await _update_job(job_id, progress=85, stats_json=stats)

        # ---- graph (85-100)：Chunk 节点的缓存键属性由 graph_writer 存 embed_key ----
        await _update_job(job_id, stage=JobStage.GRAPH)
        context_texts = {h: embed_texts[h] for h in embed_texts}
        # 把 embed_key 写进 context 映射供 graph_writer 使用：直接替换 content_hash 语义不动，
        # Chunk 节点额外携带 embed_key 属性用于下次缓存命中
        await write_project_graph(
            pid, name, git_url, project_summary, modules_info, files, chunks,
            context_texts, embeddings, api_edges,
            embed_keys=embed_keys,
        )
        await _finish(job_id, project_id, commit_sha=commit_sha)
        if partial:
            await _update_job(job_id, error_text="部分摘要生成失败，已用符号清单占位（partial）")
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
