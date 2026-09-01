"""文件归属：入口直属 + 沿 IMPORTS 边 BFS 最近归属（等距多归属）+ shared 兜底（设计 D2）。

模块唯一键 = "kind:name"（page:orders 与 api:orders 是不同模块，裸名会冲突）。
M4 B14：归属完成后对超大模块按子目录细分——1133 文件的 src 巨模块对检索与摘要都无用。
"""
from collections import deque

from app.services.ingest.router_parser import ModuleMap, RouteModule

SHARED = "shared:shared"

LARGE_MODULE_THRESHOLD = 200
MAX_SPLIT_ROUNDS = 3   # 递归细分轮数上限
MAX_MODULES = 60       # 模块数护栏：每个模块一次 L3 摘要调用，不能无限膨胀


def module_key(mod: RouteModule) -> str:
    return f"{mod.kind}:{mod.name}"


def assign_files(
    all_files: list[str],
    module_map: ModuleMap,
    imports: dict[str, set[str]],
) -> dict[str, list[str]]:
    """返回 file → [module_name]；不可达文件归 shared。

    imports: file → 它导入的文件集合（BFS 沿 import 方向向下游走）。
    """
    # 每个文件到各模块的最短距离
    dist: dict[str, dict[str, int]] = {}

    for mod in module_map.modules:
        key = module_key(mod)
        queue: deque[tuple[str, int]] = deque()
        seen: set[str] = set()
        for entry in mod.entry_files:
            if entry in imports or entry in set(all_files):
                queue.append((entry, 0))
                seen.add(entry)
        while queue:
            current, d = queue.popleft()
            best = dist.setdefault(current, {})
            if key not in best or d < best[key]:
                best[key] = d
            for target in imports.get(current, ()):  # entry imports util → util 属于该模块
                if target not in seen:
                    seen.add(target)
                    queue.append((target, d + 1))

    assignment: dict[str, list[str]] = {}
    for f in all_files:
        candidates = dist.get(f)
        if not candidates:
            assignment[f] = [SHARED]
            continue
        min_d = min(candidates.values())
        assignment[f] = sorted(m for m, d in candidates.items() if d == min_d)
    return assignment


def _files_by_module(assignment: dict[str, list[str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for path, keys in assignment.items():
        for key in keys:
            grouped.setdefault(key, []).append(path)
    return grouped


def _common_dir(paths: list[str]) -> str:
    """一组文件的最长公共目录前缀（不含文件名）。"""
    if not paths:
        return ""
    common = paths[0].split("/")[:-1]
    for path in paths[1:]:
        parts = path.split("/")[:-1]
        i = 0
        while i < len(common) and i < len(parts) and common[i] == parts[i]:
            i += 1
        common = common[:i]
        if not common:
            break
    return "/".join(common)


def next_dir_groups(paths: list[str]) -> dict[str, list[str]]:
    """按公共前缀之后的下一级目录分组；扁平目录会得到单组（即不可细分）。"""
    prefix = _common_dir(paths)
    groups: dict[str, list[str]] = {}
    for path in paths:
        rest = path[len(prefix):].lstrip("/") if prefix else path
        parts = rest.split("/")
        name = parts[0] if len(parts) > 1 else "(root)"
        groups.setdefault(name, []).append(path)
    return groups


def split_large_modules(
    module_map: ModuleMap,
    assignment: dict[str, list[str]],
    threshold: int = LARGE_MODULE_THRESHOLD,
    max_rounds: int = MAX_SPLIT_ROUNDS,
    max_modules: int = MAX_MODULES,
) -> int:
    """把 CONTAINS 文件数 > threshold 的模块按子目录细分，返回细分出的子模块数。

    就地改写 module_map.modules 与 assignment。扁平目录（无法再分）保持原样，
    模块总数达到 max_modules 后停止——细分是为了可读性，不能反过来把模块表撑爆。
    """
    created = 0
    for _ in range(max_rounds):
        grouped = _files_by_module(assignment)
        oversized = [
            m for m in module_map.modules
            if len(grouped.get(module_key(m), [])) > threshold
        ]
        if not oversized or len(module_map.modules) >= max_modules:
            break

        changed = False
        for mod in oversized:
            parent_key = module_key(mod)
            members = grouped.get(parent_key, [])
            groups = next_dir_groups(members)
            if len(groups) < 2:
                continue  # 扁平目录：不可细分（spec 明确的例外）
            if len(module_map.modules) - 1 + len(groups) > max_modules:
                continue

            entry_set = set(mod.entry_files)
            children: list[RouteModule] = []
            for sub_name, sub_files in sorted(groups.items()):
                child = RouteModule(
                    name=f"{mod.name}/{sub_name}",
                    kind=mod.kind,
                    route_prefix=mod.route_prefix,
                    entry_files=sorted(entry_set.intersection(sub_files)),
                )
                children.append(child)
                child_key = module_key(child)
                for path in sub_files:
                    keys = assignment[path]
                    assignment[path] = [
                        child_key if k == parent_key else k for k in keys
                    ]

            index = module_map.modules.index(mod)
            module_map.modules[index : index + 1] = children
            created += len(children)
            changed = True
        if not changed:
            break
    return created


def ensure_shared_module(module_map: ModuleMap, assignment: dict[str, list[str]]) -> None:
    """若有文件归属 shared 且模块表中无 shared，则补充。"""
    if any(SHARED in mods for mods in assignment.values()) and not any(
        module_key(m) == SHARED for m in module_map.modules
    ):
        module_map.modules.append(
            RouteModule(name="shared", kind="shared", route_prefix="", entry_files=[])
        )
