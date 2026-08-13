"""页面结构导图（M6 B7）：按 page 模块的路由 path 段程序化建树。

`# 产品 → ## 一级路由段 → ### 页面(path) → - 逻辑要点`，零 LLM。

要点来源优先级（D6）：
1. 该页面所属功能域的功能点（B2 产物）——最贴业务
2. 页面入口文件的 L2 摘要压缩首句
3. fast 模式或前两者都没有时：入口文件名
"""
import re

from app.services.report.features import project_tagline
from app.services.report.graph_reader import ModuleNode, ProjectTree

PAGE_KIND = "page"
MAX_POINTS_PER_PAGE = 4
MAX_POINT_CHARS = 40
MAX_PAGES_PER_SEGMENT = 30

# 反推降级时的噪音过滤：pages/ 下的这些目录放实现件不放页面
# （monorepo 实测：components/hooks 里的文件会把页面树塞满一倍）
NON_PAGE_SEGMENTS = frozenset({
    "components", "hooks", "utils", "constants", "services", "models",
    "interfaces", "typings", "types", "styles", "assets", "locales", "helpers",
})


def _entry_stem(path: str) -> str:
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if stem in ("index", "__init__", "main") and "/" in path:
        stem = path.rsplit("/", 2)[-2]
    return stem.strip("[]$_") or path


def _compress_summary(summary: str) -> str:
    """L2 摘要压缩首句：摘要是一整段话，导图节点只放第一句。"""
    text = re.split(r"[。；;\n]", (summary or "").strip())[0].strip()
    return text[:MAX_POINT_CHARS]


def route_segment(path: str) -> str:
    """一级路由段；根路径归入「首页」。"""
    parts = [p for p in (path or "").split("/") if p]
    if not parts:
        return "首页"
    head = parts[0]
    return head if not head.startswith((":", "{", "[", "*")) else "动态路由"


def _looks_like_page(entry: str) -> bool:
    """过滤实现件：components/hooks 等目录、.d.ts 类型声明、
    与所在目录同名的 PascalCase 组件（depots/Depots.tsx）。

    约定式探测器会把 pages/ 下所有文件都收进 route_paths（M4 行为），
    页面导图作为展示层在消费端过滤，不动探测器的模块划分。
    """
    segments = [s for s in entry.split("/") if s]
    if not segments:
        return False
    stem = re.sub(r"\.[a-zA-Z]+$", "", segments[-1])
    if any(s.lower() in NON_PAGE_SEGMENTS for s in segments[:-1]):
        return False
    if stem.endswith(".d"):
        return False
    if len(segments) > 1 and stem.lower() == segments[-2].lower():
        return False
    if re.match(r"^use[A-Z]", stem):  # React hooks 约定名（useColumns.tsx 平放页面目录）
        return False
    return True


def infer_route_paths(module: ModuleNode) -> list[tuple[str, str]]:
    """拿模块的页面路由；老数据没有 route_paths 时从入口文件路径反推。

    反推对约定式框架（Next/umi 的 src/pages）几乎等价，配置式路由则退化为文件路径树，
    仍比没有导图强——不必逼用户先重索引才能看到页面结构。
    """
    if module.route_paths:
        return sorted({(r, e) for r, e in module.route_paths if _looks_like_page(e)})
    inferred: list[tuple[str, str]] = []
    for node in module.files:
        path = node.path
        for marker in ("/pages/", "/views/", "/app/"):
            if marker in path:
                if not _looks_like_page(path.split(marker, 1)[1]):
                    break
                rel = path.split(marker, 1)[1]
                route = "/" + re.sub(r"\.[a-zA-Z]+$", "", rel)
                route = re.sub(r"/index$", "", route) or "/"
                inferred.append((route, path))
                break
    return sorted(set(inferred))


def page_points(
    route: str, entry: str, module: ModuleNode,
    feature_points: list[str], fast: bool,
) -> list[str]:
    """单个页面的逻辑要点。"""
    if not fast and feature_points:
        return feature_points[:MAX_POINTS_PER_PAGE]
    summary_by_path = {f.path: f.summary for f in module.files}
    summary = _compress_summary(summary_by_path.get(entry, ""))
    if not fast and summary:
        return [summary]
    return [_entry_stem(entry)] if entry else []


def build_page_map(
    tree: ProjectTree,
    points_by_key: dict[str, list[str]] | None = None,
    fast: bool = False,
) -> str:
    """页面结构导图 markdown（markmap 直接渲染）。"""
    points_by_key = points_by_key or {}
    title = f"# {tree.name or '项目'}：{project_tagline(tree)}"
    pages = [m for m in tree.modules if m.kind == PAGE_KIND]
    if not pages:
        return f"{title}\n\n> 未识别到前端页面模块。\n"

    # 一级路由段 → [(route, entry, module)]
    grouped: dict[str, list[tuple[str, str, ModuleNode]]] = {}
    for module in pages:
        for route, entry in infer_route_paths(module):
            grouped.setdefault(route_segment(route), []).append((route, entry, module))
    if not grouped:
        return f"{title}\n\n> 页面模块中没有可用的路由信息（重新索引可获取）。\n"

    lines = [title, ""]
    for segment in sorted(grouped, key=lambda s: (s == "首页" and "0" or "1", s)):
        # 按 (route, entry) 去重——ModuleNode 是 dataclass，不可 hash，不能整元组进 set
        deduped: dict[tuple[str, str], tuple[str, str, ModuleNode]] = {}
        for route, entry, module in grouped[segment]:
            deduped.setdefault((route, entry), (route, entry, module))
        entries = sorted(deduped.values(), key=lambda x: x[0])
        lines.append(f"## {segment}")
        for route, entry, module in entries[:MAX_PAGES_PER_SEGMENT]:
            lines.append(f"### {route}")
            for point in page_points(
                route, entry, module, points_by_key.get(module.key, []), fast
            ):
                lines.append(f"- {point}")
        if len(entries) > MAX_PAGES_PER_SEGMENT:
            lines.append(f"### … 另有 {len(entries) - MAX_PAGES_PER_SEGMENT} 个页面")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
