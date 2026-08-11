"""文件归属：入口直属 + 沿 IMPORTS 边 BFS 最近归属（等距多归属）+ shared 兜底（设计 D2）。

模块唯一键 = "kind:name"（page:orders 与 api:orders 是不同模块，裸名会冲突）。
"""
from collections import deque

from app.services.ingest.router_parser import ModuleMap, RouteModule

SHARED = "shared:shared"


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


def ensure_shared_module(module_map: ModuleMap, assignment: dict[str, list[str]]) -> None:
    """若有文件归属 shared 且模块表中无 shared，则补充。"""
    if any(SHARED in mods for mods in assignment.values()) and not any(
        module_key(m) == SHARED for m in module_map.modules
    ):
        module_map.modules.append(
            RouteModule(name="shared", kind="shared", route_prefix="", entry_files=[])
        )
