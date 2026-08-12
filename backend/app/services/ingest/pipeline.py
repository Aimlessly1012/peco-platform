"""索引管道编排（M3 六阶段）：clone → parse → summarize → embed → graph → report。

进度区间：clone 0-10, parse 10-25, summarize 25-55, embed 55-85, graph 85-92, report 92-100。
嵌入缓存键 = 嵌入文本 hash（embed_key）而非代码 hash——摘要/归属变化时向量随之重算。
report 阶段读图产出理解报告，任何失败只把任务标 partial，不阻塞索引成功（M3 spec）。
"""
import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import decrypt_token
from app.core.db import SessionLocal
from app.graph.client import (
    delete_files_subgraph,
    delete_modules_and_structural_edges,
    delete_project_graph,
)
from app.models.tables import IndexJob, JobStage, JobStatus, Project, ProjectStatus
from app.services.ingest.api_matcher import extract_api_edges
from app.services.ingest.chunker import ChunkError, CodeChunk, chunk_file
from app.services.ingest.deps_extractor import extract_imports
from app.services.ingest.embedder import embedder
from app.services.ingest.git_ops import (
    GitDiffError,
    GitPullError,
    diff_changed_files,
    pull_repo,
)
from app.services.ingest.graph_writer import (
    FileInfo,
    ModuleInfo,
    load_chunk_metadata,
    load_embedding_cache,
    load_file_metadata,
    load_project_index_meta,
    load_summary_cache,
    write_project_graph,
)
from app.services.ingest.module_mapper import (
    assign_files,
    ensure_shared_module,
    module_key,
    split_large_modules,
)
from app.services.ingest.progress import BatchCounter, StageProgress, batch_count
from app.services.ingest.router_parser import ModuleMap, parse_routes
from app.services.ingest.summarizer import fallback_summary, module_agg_hash, summarizer
from app.services.ingest.walker import LANGUAGE_BY_EXT, walk_repo
from app.services.report.service import generate_and_store_report

logger = logging.getLogger(__name__)

MODE_AUTO = "auto"
MODE_FULL = "full"
MODE_INCREMENTAL = "incremental"
VALID_MODES = (MODE_AUTO, MODE_FULL)


def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def embed_cache_key(text: str) -> str:
    """向量缓存键 = hash(模型:维度:嵌入文本)。

    模型标识必须进键：换嵌入模型后文本没变的 chunk 会命中旧缓存，复用上一个模型的向量，
    图里就混了两个向量空间——检索结果崩坏且极难归因。维度相同时（如 text-embedding-v3
    与 bge-m3 都是 1024）ensure_vector_index 的维度校验也拦不住，只能靠这里。
    """
    return _hash16(f"{settings.embedding_model}:{settings.embedding_dim}:{text}")


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


def partial_reason(summary_partial: bool, report_stats: dict) -> str | None:
    """汇总本次索引的降级原因（None = 全程正常）。索引仍算成功，只写进 error_text。"""
    reasons: list[str] = []
    if summary_partial:
        reasons.append("部分摘要生成失败，已用符号清单占位")
    if report_stats.get("report_error"):
        reasons.append(f"理解报告生成失败：{report_stats['report_error']}")
    elif report_stats.get("report_partial"):
        reasons.append("部分报告内容已降级（需求文档或时序图）")
    return "；".join(reasons) + "（partial）" if reasons else None


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
    repo_dir: Path, rel_files: list[Path], known_paths: set[str] | None = None
) -> tuple[list[FileInfo], list[CodeChunk], dict[str, set[str]], dict[str, str], int]:
    """解析给定文件（线程池内）：分块 + IMPORTS + 文件头。单文件失败跳过。

    known_paths 是 import 解析的目标域——必须是仓库全部可解析文件，而不是本次待解析的
    子集：增量时只解析变更文件，若用子集会把指向未变更文件的 import 全部丢掉，
    IMPORTS 边缺失又会让归属退化成 shared（图等价测试正是抓这个）。
    """
    all_rel = known_paths if known_paths is not None else {str(f) for f in rel_files}
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
    on_progress=None,
) -> tuple[dict[str, str], str, bool]:
    """生成 L2/L3/L4；返回 (module_name→L3, L4, partial)。L2 直接写入 files[].summary。

    on_progress(done, total)：口径为 L2 文件数 + L3 模块数 + 1 次 L4（M4 D6 子进度）。
    """
    file_cache, module_cache = await load_summary_cache(project_id)
    chunks_by_file: dict[str, list[CodeChunk]] = {}
    for c in chunks:
        chunks_by_file.setdefault(c.file_path, []).append(c)

    partial = False
    new_calls = 0
    cached_hits = 0
    progress_total = len(files) + len(module_map.modules) + 1
    progress_done = 0

    async def bump() -> None:
        nonlocal progress_done
        progress_done += 1
        if on_progress is not None:
            await on_progress(progress_done, progress_total)

    async def l2_for(f: FileInfo) -> None:
        nonlocal new_calls, cached_hits, partial
        if f.content_hash in file_cache:
            f.summary = file_cache[f.content_hash]
            cached_hits += 1
            await bump()
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
        await bump()

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
            await bump()
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
        await bump()

    # L4：项目总览（每次重算）
    l4 = await summarizer.summarize_project(readme, module_map, module_summaries)
    new_calls += 1
    if l4 is None:
        l4 = "（项目总览生成失败）模块列表：" + ", ".join(module_summaries)
        partial = True
    await bump()

    stats["summaries_new"] = new_calls
    stats["summaries_cached"] = cached_hits
    stats["_module_hashes"] = module_hashes
    return module_summaries, l4, partial


@dataclass
class IndexPlan:
    """一次索引要解析什么、复用什么、删什么。全量与增量的差异全部收敛在这里，
    后续阶段（路由/归属/摘要/嵌入/写图）对两种模式几乎同构（设计 D2 防漂移）。"""

    mode: str = MODE_FULL                      # full | incremental
    fallback_reason: str | None = None         # 非空表示 auto 回退全量的原因
    parse_paths: list[Path] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)
    reused_files: dict[str, FileInfo] = field(default_factory=dict)
    reused_chunks: list[CodeChunk] = field(default_factory=list)
    no_changes: bool = False
    changed_total: int = 0

    @property
    def is_incremental(self) -> bool:
        return self.mode == MODE_INCREMENTAL


async def build_index_plan(
    mode: str,
    *,
    project_id: str,
    repo_dir: Path,
    last_indexed_commit: str | None,
    commit_sha: str,
    walk_files: list[Path],
) -> IndexPlan:
    """auto 判定（设计 D3）：有基准 commit + 本地 git 副本 + diff 可执行 + 图非空 → 增量。"""
    full = IndexPlan(mode=MODE_FULL, parse_paths=list(walk_files))
    if mode == MODE_FULL:
        return full
    if not last_indexed_commit:
        full.fallback_reason = "首次索引（无基准 commit）"
        return full
    if not (repo_dir / ".git").exists():
        full.fallback_reason = "本地仓库副本缺失"
        return full
    try:
        changed = await asyncio.to_thread(
            diff_changed_files, repo_dir, last_indexed_commit, commit_sha
        )
    except GitDiffError as e:
        full.fallback_reason = str(e)
        return full

    existing = await load_file_metadata(project_id)
    if not existing:
        full.fallback_reason = "图中无该项目数据（可能被清理过）"
        return full

    # 换了嵌入模型就不能增量：未变更文件会留着上一个模型的向量，
    # 与新写入的向量不在同一个空间（M4 B15）
    meta = await load_project_index_meta(project_id)
    if (
        meta.get("embedding_model") != settings.embedding_model
        or meta.get("embedding_dim") != settings.embedding_dim
    ):
        logger.info(
            "项目 %s 嵌入模型变化（图中 %s/%s → 当前 %s/%s），强制全量重嵌入",
            project_id, meta.get("embedding_model"), meta.get("embedding_dim"),
            settings.embedding_model, settings.embedding_dim,
        )
        full.fallback_reason = "embedding_model_changed"
        return full

    if changed.is_empty():
        return IndexPlan(mode=MODE_INCREMENTAL, no_changes=True)

    walk_set = {str(p) for p in walk_files}
    # 变更文件里只有可解析的那些需要走管道；其余（如 .md/.png）只影响 last_indexed_commit
    touched = [p for p in changed.touched if p in walk_set]
    # modified 也要先删旧子图：文件里被删掉的函数会留下孤儿 Chunk
    deleted = [p for p in changed.deleted + changed.modified if p in existing]

    reused = {
        path: info
        for path, info in existing.items()
        if path not in set(touched) and path not in set(deleted) and path in walk_set
    }
    reused_chunks = await load_chunk_metadata(project_id, set(reused))
    return IndexPlan(
        mode=MODE_INCREMENTAL,
        parse_paths=[Path(p) for p in touched],
        deleted_paths=deleted,
        reused_files=reused,
        reused_chunks=reused_chunks,
        changed_total=changed.total(),
    )


def _restore_missing_imports(
    repo_dir: Path, reused: dict[str, FileInfo], all_paths: set[str]
) -> int:
    """M4 前写入的 File 节点没有 imports 属性，现场重提取（一次性成本，见 Migration）。"""
    restored = 0
    for path, info in reused.items():
        if info.imports is None:
            info.imports = sorted(extract_imports(repo_dir, Path(path), all_paths))
            restored += 1
    return restored


async def run_index_job(
    job_id: uuid.UUID, project_id: uuid.UUID, mode: str = MODE_AUTO
) -> None:
    pid = str(project_id)
    try:
        async with SessionLocal() as session:
            project = await session.get(Project, project_id)
            git_url = project.git_url
            name = project.name
            branch = project.default_branch
            last_indexed_commit = project.last_indexed_commit
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
        plan = await build_index_plan(
            mode, project_id=pid, repo_dir=repo_dir,
            last_indexed_commit=last_indexed_commit,
            commit_sha=commit_sha, walk_files=walk.files,
        )
        if plan.is_incremental:
            await _update_job(job_id, kind=MODE_INCREMENTAL)

        if plan.no_changes:
            # spec: 无变更秒级返回，不动图与报告
            await _update_job(
                job_id, progress=95,
                stats_json={
                    "mode": MODE_INCREMENTAL, "no_changes": True,
                    "files_parsed": len(walk.files),
                },
            )
            await _finish(job_id, project_id, commit_sha=commit_sha)
            logger.info("项目 %s 无变更，跳过重索引", name)
            return

        walk_paths = {str(p) for p in walk.files}
        new_files, new_chunks, imports, heads, parse_failed = await asyncio.to_thread(
            _parse_all, repo_dir, plan.parse_paths, walk_paths
        )
        imports_restored = await asyncio.to_thread(
            _restore_missing_imports, repo_dir, plan.reused_files, walk_paths
        )
        for path, info in plan.reused_files.items():
            imports[path] = set(info.imports or ())

        # 未变更部分从图读回后，与新解析的部分合成"全量视图"——
        # 路由解析、归属、CALLS_API 这些全局计算对两种模式看到的输入完全一致
        files = new_files + list(plan.reused_files.values())
        chunks = new_chunks + plan.reused_chunks
        repo_files = await asyncio.to_thread(_collect_repo_files, repo_dir, files)
        file_paths = [f.path for f in files]
        module_map = parse_routes(file_paths, repo_files)
        assignment = assign_files(file_paths, module_map, imports)
        ensure_shared_module(module_map, assignment)
        # 巨模块细分必须在归属之后：>200 的口径是 CONTAINS 文件数，不是入口文件数
        modules_split = split_large_modules(module_map, assignment)
        for f in files:
            f.modules = assignment.get(f.path, ["shared"])
            f.imports = sorted(imports.get(f.path, set()))

        chunks_by_key = {(c.file_path, c.symbol): c for c in chunks}
        frontend_chunks = [c for c in chunks if c.language != "python"]
        api_edges, api_warnings = extract_api_edges(
            frontend_chunks, module_map.backend_routes, chunks_by_key
        )
        stats = {
            "mode": plan.mode,
            "files_parsed": len(files),
            "files_skipped": walk.skipped + parse_failed,
            "chunks": len(chunks),
            "modules": len(module_map.modules),
            "api_edges": len(api_edges),
            "api_warnings": api_warnings,
            "router_fallback": module_map.fallback,
            "modules_split": modules_split,
        }
        if plan.fallback_reason:
            stats["fallback_full_reason"] = plan.fallback_reason
        if plan.is_incremental:
            stats.update(
                changed_files=plan.changed_total,
                reparsed_files=len(new_files),
                reused_files=len(plan.reused_files),
                deleted_files=len(plan.deleted_paths),
            )
            if imports_restored:
                stats["imports_restored"] = imports_restored
        await _update_job(job_id, progress=25, stats_json=stats)

        # ---- summarize (25-55)：按已完成文件/模块数连续推进（M4 D6）----
        await _update_job(job_id, stage=JobStage.SUMMARIZE)
        readme = await asyncio.to_thread(_read_readme, repo_dir)
        summarize_progress = StageProgress(
            stats, start=25, end=55, key="summarize",
            writer=lambda pct, s: _update_job(job_id, progress=pct, stats_json=s),
        )
        module_summaries, project_summary, summary_partial = await _summarize_all(
            pid, module_map, files, chunks, imports, heads, readme, stats,
            on_progress=summarize_progress,
        )
        module_hashes = stats.pop("_module_hashes", {})
        public_stats = {k: v for k, v in stats.items()}
        await _update_job(job_id, progress=55, stats_json=public_stats)

        # ---- embed (55-85)：缓存键 = 嵌入文本 hash ----
        await _update_job(job_id, stage=JobStage.EMBED)
        cache = await load_embedding_cache(pid)  # 必须在删图之前读

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
            embed_keys[c.content_hash] = embed_cache_key(text)

        # 增量：未变更文件的节点不重写，给它们算向量纯属浪费（设计 D1：向量完全不动）
        embed_chunks = new_chunks if plan.is_incremental else chunks
        embeddings: dict[str, list[float]] = {}
        to_embed: list[str] = []  # content_hash 列表
        seen: set[str] = set()
        for c in embed_chunks:
            if c.content_hash in seen:
                continue
            seen.add(c.content_hash)
            key = embed_keys[c.content_hash]
            if key in cache:
                embeddings[c.content_hash] = cache[key]
            else:
                to_embed.append(c.content_hash)
        # 三次嵌入调用（块 / 文件摘要 / 模块摘要）的批数合并成一条子进度（M4 D6）
        batch_size = settings.embedding_batch_size
        embed_progress = StageProgress(
            stats, start=55, end=85, key="embed",
            writer=lambda pct, s: _update_job(job_id, progress=pct, stats_json=s),
        )
        counter = BatchCounter(
            embed_progress,
            batch_count(len(to_embed), batch_size)
            + batch_count(len(new_files if plan.is_incremental else files), batch_size)
            + batch_count(len(module_map.modules), batch_size),
        )

        if to_embed:
            vectors = await embedder.embed_texts(
                [embed_texts[h] for h in to_embed], on_progress=counter.phase()
            )
            for h, v in zip(to_embed, vectors):
                embeddings[h] = v

        # File / Module 摘要嵌入（量小，不缓存）。增量只对要写节点的文件算
        embed_files = new_files if plan.is_incremental else files
        summary_texts = [f.summary or f.path for f in embed_files]
        file_vectors = (
            await embedder.embed_texts(summary_texts, on_progress=counter.phase())
            if embed_files else []
        )
        for f, v in zip(embed_files, file_vectors):
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
            await embedder.embed_texts(
                [m.summary or m.name for m in modules_info],
                on_progress=counter.phase(),
            )
            if modules_info else []
        )
        for m, v in zip(modules_info, module_vectors):
            m.summary_embedding = v

        stats["embedded_new"] = len(to_embed)
        stats["embedded_cached"] = len(seen) - len(to_embed)
        await _update_job(job_id, progress=85, stats_json=stats)

        # ---- graph (85-92)：Chunk 节点的缓存键属性由 graph_writer 存 embed_key ----
        await _update_job(job_id, stage=JobStage.GRAPH)
        context_texts = {h: embed_texts[h] for h in embed_texts}
        # 把 embed_key 写进 context 映射供 graph_writer 使用：直接替换 content_hash 语义不动，
        # Chunk 节点额外携带 embed_key 属性用于下次缓存命中
        if plan.is_incremental:
            # 局部删除 + 结构边全量重连（设计 D1）：Module 节点整体重建，
            # DEFINES 与未变更文件的 File/Chunk 节点原地保留
            deleted_nodes = await delete_files_subgraph(pid, plan.deleted_paths)
            await delete_modules_and_structural_edges(pid)
            stats["deleted_nodes"] = deleted_nodes
            await write_project_graph(
                pid, name, git_url, project_summary, modules_info,
                new_files, new_chunks, context_texts, embeddings, api_edges,
                embed_keys=embed_keys, edge_files=files, edge_chunks=chunks,
            )
        else:
            await delete_project_graph(pid)
            await write_project_graph(
                pid, name, git_url, project_summary, modules_info, files, chunks,
                context_texts, embeddings, api_edges,
                embed_keys=embed_keys,
            )
        await _update_job(job_id, progress=92, stats_json=stats)

        # ---- report (92-100)：读图产报告，失败只标 partial（M3 spec：不阻塞索引成功）----
        await _update_job(job_id, stage=JobStage.REPORT)
        report_stats = await generate_and_store_report(project_id)
        stats.update(report_stats)
        await _update_job(job_id, stats_json=stats)

        await _finish(job_id, project_id, commit_sha=commit_sha)
        reason = partial_reason(summary_partial, report_stats)
        if reason:
            await _update_job(job_id, error_text=reason)
        logger.info("项目 %s 索引完成: %s", name, stats)

    except GitPullError as e:
        await _finish(job_id, project_id, error=str(e))
    except Exception as e:  # noqa: BLE001 — 管道兜底，任何失败都要落库
        logger.exception("索引任务失败")
        await _finish(job_id, project_id, error=f"索引失败：{type(e).__name__}: {e}")


async def start_index_job(
    project_id: uuid.UUID, mode: str = MODE_AUTO
) -> IndexJob | None:
    """创建任务并启动后台协程；已有 running 任务返回 None（API 层转 409）。

    kind 先记为请求模式，进入管道后按实际路径改写为 full / incremental。
    """
    async with SessionLocal() as session:
        running = await session.scalar(
            select(IndexJob).where(
                IndexJob.project_id == project_id,
                IndexJob.status == JobStatus.RUNNING,
            )
        )
        if running:
            return None
        job = IndexJob(project_id=project_id, kind=MODE_FULL)
        session.add(job)
        project = await session.get(Project, project_id)
        project.status = ProjectStatus.INDEXING
        await session.commit()
        await session.refresh(job)

    asyncio.create_task(run_index_job(job.id, project_id, mode))
    return job
