"""umi 路由探测与两级降级、巨模块细分单测（M4 B13/B14）。

现场依据：ad.anynovel.app（1151 文件 umi 项目）router_fallback=true 且产出 1133 文件的
src 巨模块，检索与摘要都退化。这些用例钉住修复后的行为。
"""
from pathlib import Path

import pytest

from app.services.ingest.module_mapper import (
    LARGE_MODULE_THRESHOLD,
    assign_files,
    module_key,
    next_dir_groups,
    split_large_modules,
)
from app.services.ingest.router_parser import ModuleMap, RouteModule, parse_routes
from app.services.ingest.walker import walk_repo

FIXTURES = Path(__file__).parent / "fixtures"


def load_repo(name: str):
    repo = FIXTURES / name
    files = [str(f) for f in walk_repo(repo).files]
    repo_files = {f: (repo / f).read_text(encoding="utf-8") for f in files}
    for extra in repo.rglob("package.json"):
        rel = str(extra.relative_to(repo))
        repo_files[rel] = extra.read_text(encoding="utf-8")
    return files, repo_files


def by_key(module_map: ModuleMap) -> dict[str, RouteModule]:
    return {module_key(m): m for m in module_map.modules}


# ---------------- B13 约定式 ----------------


def test_umi_convention_detected_without_fallback():
    """spec 场景: umi 项目产出 kind=page 模块且 router_fallback 为 false。"""
    files, repo_files = load_repo("umi_convention")
    result = parse_routes(files, repo_files)

    assert result.fallback is False
    modules = by_key(result)
    assert set(modules) == {"page:home", "page:users", "page:orders"}
    assert all(m.kind == "page" for m in result.modules)


def test_umi_convention_route_prefixes_and_entries():
    files, repo_files = load_repo("umi_convention")
    modules = by_key(parse_routes(files, repo_files))

    assert modules["page:users"].route_prefix == "/users"
    assert modules["page:home"].route_prefix == "/"
    users_entries = modules["page:users"].entry_files
    assert "src/pages/users/index.tsx" in users_entries
    assert "src/pages/users/[id].tsx" in users_entries  # 动态段是路由
    assert "src/pages/users/_layout.tsx" not in users_entries  # _ 开头不是路由

    orders = modules["page:orders"].entry_files
    assert orders == ["src/pages/orders/detail.tsx", "src/pages/orders/list.tsx"]


def test_umi_convention_excludes_non_route_files():
    files, repo_files = load_repo("umi_convention")
    all_entries = {e for m in parse_routes(files, repo_files).modules for e in m.entry_files}

    assert "src/pages/components/Shared.tsx" not in all_entries  # pages 内 components 目录
    assert "src/components/Button.tsx" not in all_entries        # 不在 pages 下
    assert "src/services/api.ts" not in all_entries


@pytest.mark.parametrize(
    "path,expect_route_segment",
    [
        ("src/pages/index.tsx", "home"),
        ("src/pages/users/index.tsx", "users"),
        ("src/pages/users/[id].tsx", "users"),
        ("src/pages/orders/list.tsx", "orders"),
    ],
)
def test_umi_convention_route_mapping(path, expect_route_segment):
    from app.services.ingest.router_parser import _top_segment, _umi_convention_routes

    routes = dict((f, r) for r, f in _umi_convention_routes("", [path]))
    assert _top_segment(routes[path]) == expect_route_segment


def test_umi_dynamic_segment_forms():
    from app.services.ingest.router_parser import _umi_dynamic_segment

    assert _umi_dynamic_segment("[id]") == ":id"
    assert _umi_dynamic_segment("$id") == ":id"          # umi 3 写法
    assert _umi_dynamic_segment("[...rest]") == "*"
    assert _umi_dynamic_segment("users") == "users"


# ---------------- B13 配置式 ----------------


def test_umi_config_routes_detected():
    files, repo_files = load_repo("umi_config")
    result = parse_routes(files, repo_files)

    assert result.fallback is False
    modules = by_key(result)
    assert set(modules) == {"page:home", "page:admin"}
    assert modules["page:admin"].route_prefix == "/admin"


def test_umi_config_component_resolved_to_files():
    """component: '@/pages/admin/users' 必须解析成仓库内真实文件。"""
    files, repo_files = load_repo("umi_config")
    modules = by_key(parse_routes(files, repo_files))

    assert modules["page:admin"].entry_files == [
        "src/pages/admin/roles.tsx",
        "src/pages/admin/users.tsx",
    ]
    home = modules["page:home"].entry_files
    assert "src/pages/home/index.tsx" in home   # 目录形式 → index.tsx
    assert "src/layouts/index.tsx" in home      # 父路由 '/' 的 layout


def test_umi_nested_config_does_not_leak_child_path():
    """父对象读属性时必须剔除嵌套子对象，否则父路由会拿到子路由的 path。"""
    from app.services.ingest.router_parser import _own_props

    block = "{ path: '/', component: '@/layouts/index', routes: [{ path: '/home' }] }"
    props = _own_props(block)
    assert "'/'" in props
    assert "/home" not in props


def test_umi_config_takes_precedence_over_convention():
    """umi 配置了 routes 时约定式失效——否则 pages 下的非路由文件会被当成路由。"""
    files, repo_files = load_repo("umi_config")
    entries = {e for m in parse_routes(files, repo_files).modules for e in m.entry_files}
    # roles/users 来自配置；若走了约定式，home 模块会多出别的组合
    assert entries == {
        "src/layouts/index.tsx",
        "src/pages/home/index.tsx",
        "src/pages/admin/users.tsx",
        "src/pages/admin/roles.tsx",
    }


def test_non_umi_project_unaffected():
    """既有 Next.js + FastAPI fixture 的解析结果不受 umi 探测器插入影响。"""
    files, repo_files = load_repo("mini_repo")
    result = parse_routes(files, repo_files)

    assert result.fallback is False
    kinds = {m.kind for m in result.modules}
    assert "api" in kinds and "page" in kinds


# ---------------- B14 两级降级 ----------------


def test_fallback_prefers_page_dir_grouping():
    """降级级别 1：有 src/pages 时按其二级子目录分组，而不是一个 src 巨模块。"""
    files = (
        [f"src/pages/dashboard/view{i}.tsx" for i in range(3)]
        + [f"src/pages/settings/panel{i}.tsx" for i in range(2)]
        + ["src/pages/login.tsx", "src/utils/helper.ts", "src/components/Btn.tsx"]
    )
    result = parse_routes(files, {})

    assert result.fallback is True
    names = {m.name for m in result.modules}
    assert names == {"dashboard", "settings", "login"}
    assert all(m.kind == "page" for m in result.modules)


def test_fallback_page_dir_works_under_subroot():
    """monorepo：frontend/src/pages 也要被识别为页面目录。"""
    files = [
        "frontend/src/pages/a/x.tsx",
        "frontend/src/pages/b/y.tsx",
        "frontend/src/util.ts",
    ]
    result = parse_routes(files, {})

    assert result.fallback is True
    assert {m.name for m in result.modules} == {"a", "b"}


def test_fallback_falls_through_to_top_dirs():
    """降级级别 2：没有页面目录时退回顶层目录分组（M1 行为）。"""
    files = ["lib/a.ts", "lib/b.ts", "scripts/tool.ts", "index.ts"]
    result = parse_routes(files, {})

    assert result.fallback is True
    assert {m.name for m in result.modules} == {"lib", "scripts", "(root)"}
    assert all(m.kind == "dir" for m in result.modules)


def test_page_dir_grouping_needs_at_least_two_groups():
    """页面目录只有单组时没有细分价值，退回顶层目录分组。"""
    files = ["src/pages/only/a.tsx", "src/pages/only/b.tsx", "lib/x.ts"]
    result = parse_routes(files, {})

    assert {m.name for m in result.modules} == {"src", "lib"}


# ---------------- B14 巨模块细分 ----------------


def make_flat_assignment(module_map: ModuleMap, files: list[str]) -> dict[str, list[str]]:
    return assign_files(files, module_map, {f: set() for f in files})


def test_split_large_module_by_subdirectory():
    """spec 场景: 任何分组产生 >200 文件的模块时按子目录自动细分。"""
    files = (
        [f"src/components/c{i}.tsx" for i in range(150)]
        + [f"src/pages/p{i}.tsx" for i in range(150)]
    )
    module_map = ModuleMap(
        modules=[RouteModule(name="src", kind="dir", route_prefix="", entry_files=files)],
        fallback=True,
    )
    assignment = make_flat_assignment(module_map, files)
    assert len(assignment["src/pages/p0.tsx"]) == 1

    created = split_large_modules(module_map, assignment)

    assert created == 2
    names = {m.name for m in module_map.modules}
    assert names == {"src/components", "src/pages"}
    # 归属同步改写：文件不再指向被拆掉的父模块
    assert assignment["src/pages/p0.tsx"] == ["dir:src/pages"]
    assert assignment["src/components/c0.tsx"] == ["dir:src/components"]
    sizes = {
        module_key(m): sum(1 for keys in assignment.values() if module_key(m) in keys)
        for m in module_map.modules
    }
    assert all(size <= LARGE_MODULE_THRESHOLD for size in sizes.values())


def test_split_recurses_until_under_threshold():
    """一层不够时继续细分，直到所有模块 ≤200（spec 的最终状态要求）。"""
    files = (
        [f"src/a/x{i}.ts" for i in range(250)]
        + [f"src/b/deep/y{i}.ts" for i in range(150)]
        + [f"src/b/shallow/z{i}.ts" for i in range(150)]
    )
    module_map = ModuleMap(
        modules=[RouteModule(name="src", kind="dir", route_prefix="", entry_files=files)],
        fallback=True,
    )
    assignment = make_flat_assignment(module_map, files)

    split_large_modules(module_map, assignment)

    sizes = {
        module_key(m): sum(1 for keys in assignment.values() if module_key(m) in keys)
        for m in module_map.modules
    }
    # src/a 是扁平的 250 文件目录 → 不可细分（spec 允许的例外）
    assert sizes["dir:src/a"] == 250
    assert sizes["dir:src/b/deep"] == 150
    assert sizes["dir:src/b/shallow"] == 150


def test_split_keeps_flat_module_intact():
    """扁平目录无法细分时保持原样，不产生无意义的 (root) 单子模块。"""
    files = [f"src/f{i}.ts" for i in range(250)]
    module_map = ModuleMap(
        modules=[RouteModule(name="src", kind="dir", route_prefix="", entry_files=files)],
        fallback=True,
    )
    assignment = make_flat_assignment(module_map, files)

    assert split_large_modules(module_map, assignment) == 0
    assert [m.name for m in module_map.modules] == ["src"]


def test_split_leaves_small_modules_alone():
    files = [f"src/pages/p{i}.tsx" for i in range(10)]
    module_map = ModuleMap(
        modules=[RouteModule(name="pages", kind="page", route_prefix="/", entry_files=files)],
    )
    assignment = make_flat_assignment(module_map, files)

    assert split_large_modules(module_map, assignment) == 0
    assert len(module_map.modules) == 1


def test_split_preserves_kind_and_prefix():
    files = [f"src/pages/users/u{i}.tsx" for i in range(120)] + [
        f"src/pages/orders/o{i}.tsx" for i in range(120)
    ]
    module_map = ModuleMap(
        modules=[
            RouteModule(name="pages", kind="page", route_prefix="/app", entry_files=files)
        ],
    )
    assignment = make_flat_assignment(module_map, files)
    split_large_modules(module_map, assignment)

    assert all(m.kind == "page" for m in module_map.modules)
    assert all(m.route_prefix == "/app" for m in module_map.modules)
    assert {m.name for m in module_map.modules} == {"pages/users", "pages/orders"}


def test_split_respects_module_ceiling():
    """模块数护栏：细分不能把模块表撑爆（每模块一次 L3 摘要调用）。"""
    files = [f"src/d{i}/f{j}.ts" for i in range(80) for j in range(4)]
    module_map = ModuleMap(
        modules=[RouteModule(name="src", kind="dir", route_prefix="", entry_files=files)],
        fallback=True,
    )
    assignment = make_flat_assignment(module_map, files)
    split_large_modules(module_map, assignment)

    assert len(module_map.modules) <= 60


def test_next_dir_groups_flat_vs_nested():
    assert set(next_dir_groups(["a/b/x.ts", "a/c/y.ts"])) == {"b", "c"}
    assert set(next_dir_groups(["a/x.ts", "a/y.ts"])) == {"(root)"}
    assert set(next_dir_groups(["a/x.ts", "b/y.ts"])) == {"a", "b"}
