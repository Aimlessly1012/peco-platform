"""需求功能思维导图（M6）：功能点提取 + markdown 拼装。

产物是 markdown 层级文本（markmap 原生吃它），不是 mermaid——没有语法校验/重试链路，
"拼装"这一步属于必然成功档；只有"提取"这一步会调 LLM，且失败只降级单个功能域。
"""
import asyncio
import logging
import re

from app.services.report.graph_reader import ModuleNode, ProjectTree
from app.services.report.mindmap import KIND_LABEL

logger = logging.getLogger(__name__)

# 功能导图只收用户可感知的功能域（D4）
FEATURE_KINDS = ("page", "api")
PROGRAMMATIC_KINDS = ("dir",)   # 降级模块：程序化列路由段，不花 LLM
# 只要 1 条合格功能点就算成功：prompt 要求"宁少勿编"，闸门却因为条数少而丢弃，
# 会把单一职责模块（如 health 只有"执行健康检查"）逼成降级
MIN_POINTS = 1
MAX_POINTS = 6
MAX_POINT_CHARS = 14
MAX_ANCHORS = 15

# 输出里出现这些词说明模型滑回了技术视角，整条丢弃
TECH_WORDS = (
    "组件", "接口", "文件", "模块", "函数", "类", "路由", "封装", "渲染",
    "api", "crud", "component", "service", "util", "hook",
)
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.、)])\s*")

# 提取来源：只有 llm 结果值得进缓存，降级与 fast 产物必须每次重算
SOURCE_LLM = "llm"
SOURCE_FALLBACK = "fallback"
SOURCE_FAST = "fast"


def _clean_point(raw: str) -> str | None:
    """一行原始输出 → 合格功能点；不合格返回 None。"""
    text = BULLET_RE.sub("", (raw or "").strip())
    text = text.strip(" 　\t·:：-—") .strip()
    text = re.sub(r"[（(].*?[)）]\s*$", "", text).strip()  # 去掉尾部括号补充
    if not text or len(text) > MAX_POINT_CHARS:
        return None
    lowered = text.lower()
    if any(word in lowered for word in TECH_WORDS):
        return None
    if re.search(r"[/\\.]", text):        # 含路径或扩展名 = 没翻译成业务语言
        return None
    if re.fullmatch(r"[a-zA-Z0-9_\-\s]+", text):  # 纯英文标识符
        return None
    return text


def parse_feature_points(raw: str) -> list[str]:
    """解析 LLM 输出为功能点列表（去重、过滤技术词、限量）。"""
    points: list[str] = []
    for line in (raw or "").splitlines():
        point = _clean_point(line)
        if point and point not in points:
            points.append(point)
        if len(points) >= MAX_POINTS:
            break
    return points


def route_segment_points(module: ModuleNode, anchors: list[str]) -> list[str]:
    """程序化功能点（降级与 fast 共用）：从入口清单里取有辨识度的路径段。

    不编造业务语义——列的是真实存在的入口名，用户至少能看出这个功能域覆盖了哪些页面。
    """
    seen: list[str] = []
    for anchor in anchors:
        path = anchor.split("（", 1)[0].strip()
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if stem in ("index", "__init__", "main") and "/" in path:
            stem = path.rsplit("/", 2)[-2]
        stem = stem.strip("[]$_")
        if stem and stem not in seen:
            seen.append(stem)
        if len(seen) >= MAX_POINTS:
            break
    return seen


async def extract_module_features(
    module: ModuleNode, anchors: list[str], llm, cache: dict[str, list[str]] | None = None
) -> tuple[list[str], str]:
    """单模块功能点提取，返回 (功能点, 来源)。

    来源 llm=模型产出（可缓存）/ cache=命中缓存 / fallback=降级路由段。
    失败重试 1 次后降级——单模块失败只影响这一个功能域（spec: 不塌整图）。
    """
    trimmed = anchors[:MAX_ANCHORS]
    if cache is not None and module.agg_hash and module.agg_hash in cache:
        return cache[module.agg_hash], "cache"

    for attempt in range(2):
        try:
            raw = await llm.generate_features(
                module.name,
                KIND_LABEL.get(module.kind, module.kind),
                module.route_prefix,
                module.summary,
                "\n".join(f"- {a}" for a in trimmed),
            )
        except Exception as e:  # noqa: BLE001 — 报告不阻塞索引
            logger.warning(
                "模块 %s 功能点提取异常（%s: %s）", module.name, type(e).__name__, e
            )
            raw = None
        points = parse_feature_points(raw or "")
        if len(points) >= MIN_POINTS:
            return points, SOURCE_LLM
        logger.warning(
            "模块 %s 功能点提取产出不足（第 %d 次，得到 %d 条）",
            module.name, attempt + 1, len(points),
        )

    logger.warning("模块 %s 功能点两次提取失败，降级为入口清单", module.name)
    return route_segment_points(module, trimmed), SOURCE_FALLBACK


def feature_domains(tree: ProjectTree) -> list[ModuleNode]:
    """功能域 = kind 为 page/api 的模块；dir 降级模块也列入（程序化），shared 不入图（D4）。"""
    selected = [
        m for m in tree.modules
        if m.kind in FEATURE_KINDS or m.kind in PROGRAMMATIC_KINDS
    ]
    kind_order = {"page": 0, "api": 1, "dir": 2}
    return sorted(
        selected, key=lambda m: (kind_order.get(m.kind, 9), -len(m.files), m.name)
    )


def domain_titles(domains: list[ModuleNode]) -> dict[str, str]:
    """功能域显示名。同名的 page 与 api 并列时加 kind 后缀区分（D4）。"""
    name_counts: dict[str, int] = {}
    for module in domains:
        name_counts[module.name] = name_counts.get(module.name, 0) + 1
    titles: dict[str, str] = {}
    for module in domains:
        title = module.name
        if name_counts[module.name] > 1:
            title = f"{module.name}（{KIND_LABEL.get(module.kind, module.kind)}）"
        titles[module.key] = title
    return titles


def project_tagline(tree: ProjectTree) -> str:
    """产品定位一句：取 L4 总览里的「项目定位」行，取不到就用首句。"""
    summary = (tree.summary or "").strip()
    if not summary:
        return "代码仓库功能概览"
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith("项目定位"):
            return line.split("：", 1)[-1].split(":", 1)[-1].strip() or line
    first = re.split(r"[。\n]", summary)[0].strip()
    return first[:60] or "代码仓库功能概览"


def build_feature_map(
    tree: ProjectTree, points_by_key: dict[str, list[str]]
) -> str:
    """拼装三层 markdown：# 项目名：定位 → ## 功能域 → - 功能点（M6 D2）。"""
    title = f"# {tree.name or '项目'}：{project_tagline(tree)}"
    domains = feature_domains(tree)
    if not domains:
        return f"{title}\n\n> 暂未识别到用户功能模块（可能是纯工具库或索引未完成）。\n"

    titles = domain_titles(domains)
    lines = [title, ""]
    for module in domains:
        lines.append(f"## {titles[module.key]}")
        points = points_by_key.get(module.key) or []
        if points:
            lines.extend(f"- {p}" for p in points)
        else:
            lines.append("- （暂未提取到功能点）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def generate_feature_map(
    tree: ProjectTree,
    anchors_by_key: dict[str, list[str]],
    llm,
    cache: dict[str, list[str]] | None = None,
    fast: bool = False,
) -> tuple[str, dict[str, list[str]], dict]:
    """生成功能导图，返回 (markdown, 可缓存的功能点, stats)。

    fast 模式与 dir 降级模块全程序化（零 LLM）；page/api 模块每个一次小调用，并发执行。
    """
    domains = feature_domains(tree)
    stats = {"feature_domains": len(domains), "feature_points_new": 0,
             "feature_points_cached": 0, "feature_points_fallback": 0}
    if not domains:
        return build_feature_map(tree, {}), {}, stats

    async def for_module(module: ModuleNode) -> tuple[str, list[str], str]:
        anchors = anchors_by_key.get(module.key, [])
        if fast or module.kind in PROGRAMMATIC_KINDS:
            return module.key, route_segment_points(module, anchors[:MAX_ANCHORS]), (
                SOURCE_FAST if fast else SOURCE_FALLBACK
            )
        points, source = await extract_module_features(module, anchors, llm, cache)
        return module.key, points, source

    results = await asyncio.gather(*(for_module(m) for m in domains))

    points_by_key: dict[str, list[str]] = {}
    cacheable: dict[str, list[str]] = {}
    for key, points, source in results:
        points_by_key[key] = points
        if source == SOURCE_LLM:
            stats["feature_points_new"] += 1
            module = next((m for m in domains if m.key == key), None)
            if module is not None and module.agg_hash and points:
                cacheable[module.agg_hash] = points
        elif source == "cache":
            stats["feature_points_cached"] += 1
        else:
            stats["feature_points_fallback"] += 1

    return build_feature_map(tree, points_by_key), cacheable, stats
