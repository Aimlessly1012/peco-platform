"""报告内容构建（设计 D1）：核心模块筛选、LLM 输入拼装、校验重试与降级。

本模块只依赖图数据 dataclass 与一个 llm 对象（可注入 mock），不碰 Neo4j / Postgres，
便于单测覆盖校验器与全部降级路径。
"""
import asyncio
import logging
from dataclasses import dataclass, field

from app.services.report.graph_reader import FileNode, GraphEdges, ModuleNode, ProjectTree
from app.services.report.mermaid_check import strip_fence, validate_sequence
from app.services.report.mindmap import KIND_LABEL

logger = logging.getLogger(__name__)

CORE_MODULE_KINDS = {"api", "page"}
CORE_MIN_FILES = 2
MAX_CORE_MODULES = 6
# M5 D4：时序图输入瘦身——入口 ≤5、每类边 ≤15，超限截断并在 prompt 注明只给主链路
MAX_ENTRY_FILES = 5
MAX_EDGE_LINES = 15
# M5 D3：文档 map-reduce 的批大小。49 个 L3 塞一个 prompt 必然超限，整篇塌方
MAX_MODULES_PER_BATCH = 10


@dataclass
class ModuleContext:
    """单个模块的时序图输入（模块 L3 + 入口文件 L2 + 相关边清单）。"""

    module: ModuleNode
    entry_files: list[FileNode] = field(default_factory=list)
    api_lines: list[str] = field(default_factory=list)
    import_lines: list[str] = field(default_factory=list)

    @property
    def entry_summaries(self) -> str:
        return "\n".join(
            f"- {f.path}：{f.summary or '（无摘要）'}" for f in self.entry_files
        )


def select_core_modules(
    tree: ProjectTree, limit: int = MAX_CORE_MODULES
) -> list[ModuleNode]:
    """核心模块筛选（spec）：kind 为 api/page 且 CONTAINS 文件数 ≥2，按文件数降序取前 limit。"""
    candidates = [
        m for m in tree.modules
        if m.kind in CORE_MODULE_KINDS and len(m.files) >= CORE_MIN_FILES
    ]
    candidates.sort(key=lambda m: (-len(m.files), m.kind, m.name))
    return candidates[:limit]


def _rank_edges(edges: list, entry_paths: set[str], key) -> list:
    """入口文件相关的边排前面——时序图要画的是主链路，不是模块内全部依赖。"""
    return sorted(edges, key=lambda e: 0 if key(e) & entry_paths else 1)


def build_module_context(mod: ModuleNode, edges: GraphEdges) -> ModuleContext:
    """挑入口文件 + 抽取以入口为中心的 CALLS_API / IMPORTS 边清单（M5 D4 瘦身）。"""
    paths = {f.path for f in mod.files}

    api_edges = [
        e for e in edges.api_edges
        if e.src_file in paths or e.dst_file in paths
    ]
    import_edges = [e for e in edges.import_edges if e.src in paths]

    endpoint_files = {e.src_file for e in api_edges} | {e.dst_file for e in api_edges}
    out_degree: dict[str, int] = {}
    for e in import_edges:
        out_degree[e.src] = out_degree.get(e.src, 0) + 1

    def score(f: FileNode) -> tuple:
        return (
            -(4 if f.path in endpoint_files else 0),
            -out_degree.get(f.path, 0),
            f.path,
        )

    entry_files = sorted(mod.files, key=score)[:MAX_ENTRY_FILES]
    entry_paths = {f.path for f in entry_files}

    ranked_api = _rank_edges(api_edges, entry_paths, lambda e: {e.src_file, e.dst_file})
    ranked_imports = _rank_edges(import_edges, entry_paths, lambda e: {e.src})

    api_lines = [
        f"{e.src_file}:{e.src_symbol}(L{e.src_start}) --HTTP--> "
        f"{e.dst_file}:{e.dst_symbol}(L{e.dst_start})"
        for e in ranked_api[:MAX_EDGE_LINES]
    ]
    import_lines = [f"{e.src} → {e.dst}" for e in ranked_imports[:MAX_EDGE_LINES]]
    # 截断时明确告诉模型"这只是主链路"，避免它以为看到了全貌而编造收尾步骤
    if len(ranked_api) > MAX_EDGE_LINES:
        api_lines.append(
            f"（仅列出主链路前 {MAX_EDGE_LINES} 条，模块内共 {len(ranked_api)} 条）"
        )
    if len(ranked_imports) > MAX_EDGE_LINES:
        import_lines.append(
            f"（仅列出主链路前 {MAX_EDGE_LINES} 条，模块内共 {len(ranked_imports)} 条）"
        )
    return ModuleContext(
        module=mod, entry_files=entry_files,
        api_lines=api_lines, import_lines=import_lines,
    )


def build_fallback_text(ctx: ModuleContext) -> str:
    """时序图降级：程序化文字版调用链路（必定可读，零 LLM）。"""
    mod = ctx.module
    label = KIND_LABEL.get(mod.kind, mod.kind)
    lines = [f"模块 {mod.name}（{label}{'，路由 ' + mod.route_prefix if mod.route_prefix else ''}）调用链路："]
    if ctx.api_lines:
        lines.append("")
        lines.append("前后端调用：")
        lines.extend(f"{i}. {line}" for i, line in enumerate(ctx.api_lines, 1))
    if ctx.import_lines:
        lines.append("")
        lines.append("文件依赖：")
        lines.extend(f"{i}. {line}" for i, line in enumerate(ctx.import_lines, 1))
    if not ctx.api_lines and not ctx.import_lines:
        lines.append("")
        lines.append("核心文件：")
        lines.extend(
            f"{i}. {f.path}：{f.summary or '（无摘要）'}"
            for i, f in enumerate(ctx.entry_files, 1)
        )
    return "\n".join(lines)


def build_module_lines(tree: ProjectTree) -> str:
    """路由地图结构化文本（需求逻辑文档输入之一）。"""
    return "\n".join(
        f"- [{m.kind}] {m.name}（路由 {m.route_prefix or '无'}，{len(m.files)} 个文件）"
        f"：{', '.join(f.path for f in m.files[:6])}"
        for m in tree.modules
    )


def build_module_summaries(tree: ProjectTree) -> str:
    return "\n\n".join(
        f"## [{m.kind}] {m.name}\n{m.summary or '（无摘要）'}" for m in tree.modules
    )


def fallback_doc(tree: ProjectTree) -> str:
    """需求逻辑文档降级（spec）：L4 总览 + 各模块 L3 原文拼接，仍是可读 Markdown。"""
    parts = [
        f"# {tree.name or '项目'} 需求逻辑文档",
        "",
        "> 本文档由文档生成模型调用失败后自动降级产出，内容为索引阶段的原始摘要拼接。",
        "",
        "## 一、系统概述",
        "",
        tree.summary or "（暂无项目总览）",
        "",
        "## 二、功能模块需求",
    ]
    for m in tree.modules:
        label = KIND_LABEL.get(m.kind, m.kind)
        prefix = f"，路由 {m.route_prefix}" if m.route_prefix else ""
        parts += ["", f"### [{label}] {m.name}{prefix}", "", m.summary or "（暂无模块摘要）"]
        if m.files:
            parts += ["", "关键文件："]
            parts += [f"- {f.path}" for f in m.files[:15]]
            if len(m.files) > 15:
                parts.append(f"- … 其余 {len(m.files) - 15} 个文件")
    return "\n".join(parts) + "\n"


def split_module_batches(
    tree: ProjectTree, batch_size: int = MAX_MODULES_PER_BATCH
) -> list[list[ModuleNode]]:
    """按 kind 分组后切批（M5 D3）：同批模块类型一致，章节风格更稳。"""
    by_kind: dict[str, list[ModuleNode]] = {}
    for mod in tree.modules:
        by_kind.setdefault(mod.kind, []).append(mod)

    kind_order = {"api": 0, "page": 1, "dir": 2, "shared": 3}
    batches: list[list[ModuleNode]] = []
    for kind in sorted(by_kind, key=lambda k: (kind_order.get(k, 9), k)):
        members = sorted(by_kind[kind], key=lambda m: (-len(m.files), m.name))
        for i in range(0, len(members), batch_size):
            batches.append(members[i : i + batch_size])
    return batches


def build_batch_input(modules: list[ModuleNode]) -> str:
    """一批模块的 LLM 输入：L3 摘要 + 关键文件清单。"""
    blocks = []
    for mod in modules:
        label = KIND_LABEL.get(mod.kind, mod.kind)
        files = ", ".join(f.path for f in mod.files[:10])
        more = f" 等 {len(mod.files)} 个文件" if len(mod.files) > 10 else ""
        blocks.append(
            f"模块名：{mod.name}\n"
            f"类型：{label}\n"
            f"路由前缀：{mod.route_prefix or '无'}\n"
            f"职责摘要：{mod.summary or '（无摘要）'}\n"
            f"关键文件：{files}{more}"
        )
    return "\n\n---\n\n".join(blocks)


def fallback_chapters(modules: list[ModuleNode]) -> str:
    """单批失败时只降级这一批（M5 spec：批为降级粒度）。"""
    parts = []
    for mod in modules:
        label = KIND_LABEL.get(mod.kind, mod.kind)
        prefix = f"，路由 {mod.route_prefix}" if mod.route_prefix else ""
        parts.append(f"### {mod.name}（{label}{prefix}）")
        parts.append("")
        parts.append("> 本节由模型调用失败后自动降级产出，内容为索引阶段的原始摘要。")
        parts.append("")
        parts.append(mod.summary or "（暂无模块摘要）")
        if mod.files:
            parts.append("")
            parts.append("**关键文件**：")
            parts += [f"- {f.path}" for f in mod.files[:15]]
            if len(mod.files) > 15:
                parts.append(f"- … 其余 {len(mod.files) - 15} 个文件")
        parts.append("")
    return "\n".join(parts)


def chapter_titles(tree: ProjectTree) -> str:
    return "\n".join(
        f"- {m.name}（{KIND_LABEL.get(m.kind, m.kind)}）" for m in tree.modules
    )


async def _generate_one_batch(modules: list[ModuleNode], llm) -> tuple[str, bool]:
    """返回 (章节 markdown, 是否降级)。单批失败只影响本批。"""
    try:
        text = await llm.generate_chapters(build_batch_input(modules), len(modules))
    except Exception as e:  # noqa: BLE001 — 报告不阻塞索引
        logger.warning("文档章节批次异常（%s: %s），该批降级拼接", type(e).__name__, e)
        text = None
    if not text or not text.strip():
        logger.warning("文档章节批次未产出内容（%d 个模块），该批降级拼接", len(modules))
        return fallback_chapters(modules), True
    body = strip_fence(text) if text.strip().startswith("```") else text.strip()
    return body, False


async def generate_doc(tree: ProjectTree, llm) -> tuple[str, bool]:
    """map-reduce 生成需求逻辑文档（M5 D3）。返回 (doc_markdown, 是否整篇降级)。

    map：模块分批并发生成章节；reduce：以章节清单生成系统概述。
    单批失败只降级该批，全部批失败才算整篇降级——这是修掉"49 个 L3 塞单 prompt
    导致整篇塌成拼接"的根因所在。
    """
    batches = split_module_batches(tree)
    if not batches:
        return fallback_doc(tree), True

    results = await asyncio.gather(
        *(_generate_one_batch(batch, llm) for batch in batches)
    )
    chapters = [text for text, _ in results]
    degraded_batches = sum(1 for _, degraded in results if degraded)
    all_degraded = degraded_batches == len(batches)

    overview = ""
    if not all_degraded:
        try:
            overview = await llm.generate_overview(
                tree.summary, build_module_lines(tree), chapter_titles(tree)
            ) or ""
        except Exception as e:  # noqa: BLE001
            logger.warning("系统概述生成异常（%s: %s），用总览原文", type(e).__name__, e)
    if not overview.strip():
        overview = f"## 一、系统概述\n\n{tree.summary or '（暂无项目总览）'}"
    elif overview.strip().startswith("```"):
        overview = strip_fence(overview)

    doc = "\n\n".join(
        [
            f"# {tree.name or '项目'} 需求逻辑文档",
            overview.strip(),
            "## 二、功能模块需求",
            "\n\n".join(chapter.strip() for chapter in chapters if chapter.strip()),
        ]
    )
    if degraded_batches:
        doc += (
            f"\n\n> 说明：本次生成中有 {degraded_batches}/{len(batches)} 批模块章节"
            f"因模型调用失败降级为原始摘要拼接。\n"
        )
    return doc + "\n", all_degraded


async def generate_one_sequence(ctx: ModuleContext, llm) -> dict:
    """单模块时序图：LLM → 启发式校验 → 失败重试 1 次 → fallback_text 降级。"""
    mod = ctx.module
    item = {
        "module_key": mod.key,
        "module_name": mod.name,
        "kind": mod.kind,
        "route_prefix": mod.route_prefix,
        "mermaid": "",
        "fallback_text": build_fallback_text(ctx),
    }
    reason = ""
    for attempt in range(2):  # spec: 校验失败自动重试 1 次
        try:
            raw = await llm.generate_sequence(
                mod.name, mod.kind, mod.route_prefix, mod.summary,
                ctx.entry_summaries,
                "\n".join(ctx.api_lines), "\n".join(ctx.import_lines),
                retry_reason=reason,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("模块 %s 时序图调用异常（%s）", mod.name, type(e).__name__)
            raw = None
        if not raw:
            reason = "模型未返回内容"
            continue
        body = strip_fence(raw)
        ok, reason = validate_sequence(body)
        if ok:
            item["mermaid"] = body
            return item
        logger.warning(
            "模块 %s 时序图校验失败（第 %d 次）：%s", mod.name, attempt + 1, reason
        )
    logger.warning("模块 %s 时序图两次均失败，降级为文字链路", mod.name)
    return item


async def generate_sequences(
    tree: ProjectTree, edges: GraphEdges, llm
) -> tuple[list[dict], int, int]:
    """返回 (sequences, ok 数, fallback 数)。单图失败不影响其他（spec）。"""
    modules = select_core_modules(tree)
    if not modules:
        return [], 0, 0
    contexts = [build_module_context(m, edges) for m in modules]
    sequences = list(
        await asyncio.gather(*(generate_one_sequence(c, llm) for c in contexts))
    )
    ok = sum(1 for s in sequences if s["mermaid"])
    return sequences, ok, len(sequences) - ok
