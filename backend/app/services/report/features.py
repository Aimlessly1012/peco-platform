"""需求功能思维导图（M6）：功能点提取 + markdown 拼装。

产物是 markdown 层级文本（markmap 原生吃它），不是 mermaid——没有语法校验/重试链路，
"拼装"这一步属于必然成功档；只有"提取"这一步会调 LLM，且失败只降级单个功能域。
"""
import asyncio
import hashlib
import json
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

# ---- 业务归组（M6 B6）----
GROUP_THRESHOLD = 8    # 功能域 >8 才归组：少于这个数平铺本来就看得过来
MIN_GROUPS = 3
MAX_GROUPS = 10
OTHER_GROUP = "其他"
GROUP_TECH_WORDS = ("模块", "服务", "组件", "接口", "页面", "后台", "前端", "module", "service")
JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)


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
    """产品定位一句：取 L4 总览里的「项目定位」行，取不到就用首句。

    L4 为降级/失败占位（含"生成失败"或以「（」开头的占位串）时不上标题——
    根节点串进 "（项目总览生成失败）模块列表：page:xxx" 这类技术残片非常难看。
    """
    summary = (tree.summary or "").strip()
    if not summary or "生成失败" in summary[:20]:
        return "代码仓库功能概览"
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith("项目定位"):
            return line.split("：", 1)[-1].split(":", 1)[-1].strip() or line
    first = re.split(r"[。\n]", summary)[0].strip()
    if "生成失败" in first or first.startswith("（"):
        return "代码仓库功能概览"
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
    group_cache: dict[str, dict[str, list[str]]] | None = None,
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

    # M6 B6：功能域多时加「业务组」层，49 个平铺一排读不了
    titles = domain_titles(domains)
    groups, group_source = (
        ({}, "none") if fast
        else await group_feature_domains(domains, titles, llm, cache=group_cache)
    )
    stats["feature_groups"] = len(groups)
    stats["feature_groups_source"] = group_source
    if groups:
        markdown = build_grouped_feature_map(tree, points_by_key, groups)
    else:
        markdown = build_feature_map(tree, points_by_key)
    stats["_feature_groups"] = groups if group_source == "llm" else {}
    stats["_feature_groups_sig"] = domains_signature(domains)
    stats["_points_by_key"] = points_by_key   # 页面导图要按 module.key 取功能点
    return markdown, cacheable, stats


# ---------------- 功能域业务归组（M6 B6） ----------------


def domains_signature(domains: list[ModuleNode]) -> str:
    """归组缓存键：功能域名称集合的 hash——模块结构没变就复用上次的归组。"""
    joined = "|".join(sorted(f"{m.kind}:{m.name}" for m in domains))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def build_group_input(domains: list[ModuleNode], titles: dict[str, str]) -> str:
    """归组输入：功能域名 + 类型 + L3 业务目标首句。"""
    lines = []
    for module in domains:
        goal = ""
        for line in (module.summary or "").splitlines():
            if line.strip().startswith("业务目标"):
                goal = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                break
        if not goal:
            goal = re.split(r"[。\n]", (module.summary or "").strip())[0][:40]
        lines.append(
            f"- {titles[module.key]}（{KIND_LABEL.get(module.kind, module.kind)}）"
            f"：{goal or '（无摘要）'}"
        )
    return "\n".join(lines)


def parse_groups(raw: str) -> dict[str, list[str]]:
    """解析归组 JSON（容忍围栏与前后缀文字）。"""
    text = (raw or "").strip()
    if not text:
        return {}
    match = JSON_BLOCK_RE.search(text)
    if match is None:
        return {}
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    groups: dict[str, list[str]] = {}
    for name, members in data.items():
        if not isinstance(name, str) or not isinstance(members, list):
            continue
        clean = [m.strip() for m in members if isinstance(m, str) and m.strip()]
        if clean:
            groups[name.strip()] = clean
    return groups


def _suffix_match(member: str, titles: list[str]) -> str | None:
    """路径型域名容错：monorepo 的域名是 a/src/pages/b 这类长路径，
    LLM 即使被要求逐字复制也常简写成尾段——唯一后缀才映射，歧义不赌。"""
    hits = [t for t in titles if t.endswith("/" + member)]
    return hits[0] if len(hits) == 1 else None


def validate_groups(
    groups: dict[str, list[str]], valid_titles: list[str]
) -> tuple[dict[str, list[str]], str]:
    """归组校验（防幻觉核心）：成员必须真实存在、不重复；遗漏的进「其他」。

    返回 (清洗后的分组, 失败原因)。失败原因非空时调用方降级为平铺。
    """
    if not groups:
        return {}, "未解析出分组"
    allowed = set(valid_titles)
    seen: set[str] = set()
    cleaned: dict[str, list[str]] = {}
    dropped = 0
    for name, members in groups.items():
        if any(word in name.lower() for word in GROUP_TECH_WORDS):
            return {}, f"组名含技术词：{name}"
        kept = []
        for member in members:
            resolved = member if member in allowed else _suffix_match(member, valid_titles)
            if resolved is None or resolved in seen:
                dropped += 1
                continue
            seen.add(resolved)
            kept.append(resolved)
        if kept:
            cleaned[name] = kept

    missing = [title for title in valid_titles if title not in seen]
    if missing:
        cleaned.setdefault(OTHER_GROUP, []).extend(missing)
    if not cleaned:
        return {}, "所有成员都不在功能域清单内"
    if len(cleaned) < 2:
        return {}, "只归出一个组，归组无意义"
    # 幻觉先判：它的诊断信息比"归类太少"更能定位问题
    if dropped and dropped > len(valid_titles) // 2:
        return {}, f"过半成员（{dropped}）不在清单内，疑似幻觉"
    # 绝大多数都落进「其他」时，这棵树等于平铺加一个杂物筐——不如老老实实平铺。
    # 阈值取 1/3：真实项目总有一批零散功能，但主干必须成形
    grouped = sum(len(v) for name, v in cleaned.items() if name != OTHER_GROUP)
    if grouped * 3 < len(valid_titles):
        return {}, f"仅 {grouped}/{len(valid_titles)} 个功能域被归类，归组无意义"
    return cleaned, ""


async def group_feature_domains(
    domains: list[ModuleNode], titles: dict[str, str], llm,
    cache: dict[str, dict[str, list[str]]] | None = None,
) -> tuple[dict[str, list[str]], str]:
    """返回 (分组, 来源)。来源 llm / cache / none（none = 保持平铺）。"""
    if len(domains) <= GROUP_THRESHOLD:
        return {}, "none"

    signature = domains_signature(domains)
    if cache and signature in cache:
        return cache[signature], "cache"

    valid_titles = [titles[m.key] for m in domains]
    # 推理型模型对大清单归类波动大（偶发空输出/归类过粗）——失败再试一次，
    # 与业务流程图同款设计；两次都不行才降级平铺
    for attempt in range(2):
        try:
            raw = await llm.group_domains(
                build_group_input(domains, titles), len(domains),
                min_groups=MIN_GROUPS, max_groups=MAX_GROUPS,
            )
        except Exception as e:  # noqa: BLE001 — 归组失败只降级为平铺
            logger.warning("功能域归组异常（%s: %s）", type(e).__name__, e)
            raw = None
        groups, reason = validate_groups(parse_groups(raw or ""), valid_titles)
        if not reason:
            return groups, "llm"
        logger.warning(
            "功能域归组失败（%s），%s", reason,
            "重试一次" if attempt == 0 else "保持平铺三层",
        )
    return {}, "none"


def build_grouped_feature_map(
    tree: ProjectTree,
    points_by_key: dict[str, list[str]],
    groups: dict[str, list[str]],
) -> str:
    """四层 markdown：# 产品 → ## 业务组 → ### 功能域 → - 功能点（M6 D5）。"""
    domains = feature_domains(tree)
    titles = domain_titles(domains)
    by_title = {titles[m.key]: m for m in domains}

    lines = [f"# {tree.name or '项目'}：{project_tagline(tree)}", ""]
    for group_name, members in groups.items():
        lines.append(f"## {group_name}")
        for title in members:
            module = by_title.get(title)
            if module is None:
                continue
            lines.append(f"### {title}")
            points = points_by_key.get(module.key) or []
            lines.extend(f"- {p}" for p in points) if points else lines.append(
                "- （暂未提取到功能点）"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
