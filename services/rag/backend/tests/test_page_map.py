"""页面结构导图单测（M6 B7）：路由建树、要点来源优先级与老数据反推。"""
import pytest

from app.services.report.graph_reader import FileNode, ModuleNode, ProjectTree
from app.services.report.pagemap import (
    build_page_map,
    infer_route_paths,
    page_points,
    route_segment,
)


def page_tree(with_routes: bool = True) -> ProjectTree:
    orders = ModuleNode(
        key="page:orders", name="orders", kind="page", route_prefix="/orders",
        summary="业务目标：订单页",
        files=[
            FileNode(path="src/pages/orders/index.tsx", summary="订单列表页，展示全部订单。含筛选"),
            FileNode(path="src/pages/orders/[id].tsx", summary="订单详情页"),
        ],
        route_paths=[("/orders", "src/pages/orders/index.tsx"),
                     ("/orders/:id", "src/pages/orders/[id].tsx")] if with_routes else [],
    )
    home = ModuleNode(
        key="page:home", name="home", kind="page", route_prefix="/",
        files=[FileNode(path="src/pages/index.tsx", summary="首页")],
        route_paths=[("/", "src/pages/index.tsx")] if with_routes else [],
    )
    api = ModuleNode(
        key="api:orders", name="orders", kind="api", route_prefix="/api/orders",
        files=[FileNode(path="backend/routers/orders.py")],
    )
    return ProjectTree(
        project_id="p", name="mini-shop", summary="项目定位：订单系统",
        modules=[orders, home, api],
    )


# ---------------- 路由段与建树 ----------------


@pytest.mark.parametrize(
    "path,expect",
    [
        ("/", "首页"), ("", "首页"),
        ("/orders", "orders"), ("/orders/:id", "orders"),
        ("/:id", "动态路由"), ("/[slug]/detail", "动态路由"),
    ],
)
def test_route_segment(path, expect):
    assert route_segment(path) == expect


def test_build_page_map_three_levels():
    markdown = build_page_map(page_tree())
    lines = markdown.splitlines()

    assert lines[0].startswith("# mini-shop：")
    assert "## orders" in markdown
    assert "### /orders" in markdown
    assert "### /orders/:id" in markdown
    # 首页排在最前
    assert lines.index("## 首页") < lines.index("## orders")


def test_page_map_excludes_api_modules():
    """页面导图只讲前端页面，接口模块不入图。"""
    markdown = build_page_map(page_tree())
    assert "backend/routers/orders.py" not in markdown
    assert "## api" not in markdown


def test_page_map_without_page_modules():
    tree = ProjectTree(
        project_id="p", name="api-only", summary="项目定位：纯后端",
        modules=[ModuleNode(key="api:orders", name="orders", kind="api")],
    )
    assert "未识别到前端页面模块" in build_page_map(tree)


def test_page_map_without_route_info():
    """page 模块存在但拿不到任何路由（文件不在 pages 目录下）。"""
    tree = ProjectTree(
        project_id="p", name="x", summary="项目定位：x",
        modules=[ModuleNode(key="page:a", name="a", kind="page",
                            files=[FileNode(path="src/widgets/a.tsx")])],
    )
    assert "没有可用的路由信息" in build_page_map(tree)


# ---------------- 老数据反推 ----------------


def test_infer_route_paths_uses_stored_routes():
    module = page_tree().modules[0]
    assert ("/orders/:id", "src/pages/[id].tsx") not in infer_route_paths(module)
    assert ("/orders", "src/pages/orders/index.tsx") in infer_route_paths(module)


def test_infer_route_paths_falls_back_to_file_paths():
    """M6 之前索引的项目 Module 上没有 route_paths，从入口文件反推。"""
    module = page_tree(with_routes=False).modules[0]
    routes = dict(infer_route_paths(module))

    assert routes["/orders"] == "src/pages/orders/index.tsx"      # index 归父路径
    assert routes["/orders/[id]"] == "src/pages/orders/[id].tsx"


def test_page_map_works_on_legacy_data():
    """不重索引也能看到页面结构（只是动态段仍是文件写法）。"""
    markdown = build_page_map(page_tree(with_routes=False))
    assert "## orders" in markdown
    assert "### /orders" in markdown


def test_infer_skips_non_page_implementation_files():
    """反推降级只收页面：components/hooks 等实现目录与 .d.ts 类型声明不入树。"""
    module = ModuleNode(
        key="page:depots", name="depots", kind="page",
        files=[
            FileNode(path="src/pages/depots/index.tsx"),
            FileNode(path="src/pages/depots/components/addInventoryModal.tsx"),
            FileNode(path="src/pages/depots/hooks/useDepots.ts"),
            FileNode(path="src/pages/depots/interface.d.ts"),
            FileNode(path="src/pages/depots/utils/format.ts"),
            FileNode(path="src/pages/depots/useColumns.tsx"),  # hooks 平放页面目录
        ],
    )
    routes = [r for r, _ in infer_route_paths(module)]
    assert routes == ["/depots"]


def test_infer_skips_component_named_after_directory():
    """depots/Depots.tsx 是页面实现组件不是另一个页面。"""
    module = ModuleNode(
        key="page:depots", name="depots", kind="page",
        files=[
            FileNode(path="src/pages/depots/index.tsx"),
            FileNode(path="src/pages/depots/Depots.tsx"),
            FileNode(path="src/pages/depots/information/Information.tsx"),
        ],
    )
    routes = [r for r, _ in infer_route_paths(module)]
    assert routes == ["/depots"]


def test_stored_route_paths_also_filtered():
    """约定式探测器把 pages/ 下实现件也写进了 route_paths（M4 行为）——
    存量路由同样要过滤，只留真实页面。"""
    module = ModuleNode(
        key="page:subject", name="subject", kind="page",
        files=[FileNode(path="src/pages/subject/index.ts")],
        route_paths=[
            ("/subject", "src/pages/subject/index.ts"),
            ("/subject/Subject", "src/pages/subject/Subject.tsx"),
            ("/subject/components/editModal", "src/pages/subject/components/editModal.tsx"),
            ("/subject/interface.d", "src/pages/subject/interface.d.ts"),
        ],
    )
    assert infer_route_paths(module) == [("/subject", "src/pages/subject/index.ts")]


# ---------------- 要点来源优先级 ----------------


def test_points_prefer_feature_points():
    """D6 优先级 1：所属功能域的功能点（B2 产物）。"""
    tree = page_tree()
    markdown = build_page_map(tree, points_by_key={"page:orders": ["浏览订单列表", "查看订单详情"]})

    assert "- 浏览订单列表" in markdown
    assert "- 订单列表页，展示全部订单" not in markdown   # 没退到 L2


def test_points_fall_back_to_compressed_summary():
    """D6 优先级 2：L2 摘要压缩首句（在句号处截断）。"""
    module = page_tree().modules[0]
    points = page_points("/orders", "src/pages/orders/index.tsx", module, [], fast=False)

    assert points == ["订单列表页，展示全部订单"]


def test_points_fall_back_to_entry_stem_when_no_summary():
    module = ModuleNode(
        key="page:a", name="a", kind="page",
        files=[FileNode(path="src/pages/a/index.tsx", summary="")],
    )
    assert page_points("/a", "src/pages/a/index.tsx", module, [], fast=False) == ["a"]


def test_fast_mode_uses_entry_file_names():
    """spec: fast 模式要点退化为入口文件名。"""
    tree = page_tree()
    markdown = build_page_map(
        tree, points_by_key={"page:orders": ["浏览订单列表"]}, fast=True
    )

    assert "- 浏览订单列表" not in markdown
    assert "- orders" in markdown or "- id" in markdown


def test_points_are_capped():
    module = page_tree().modules[0]
    many = [f"功能{i}" for i in range(10)]
    points = page_points("/orders", "src/pages/orders/index.tsx", module, many, fast=False)
    assert len(points) <= 4


def test_page_map_is_valid_markdown_hierarchy():
    markdown = build_page_map(page_tree(), points_by_key={"page:orders": ["浏览订单列表"]})
    for line in markdown.splitlines():
        if line.startswith("#"):
            assert line.lstrip("#").startswith(" ")
            assert line.lstrip("# ").strip()
        elif line.startswith("-"):
            assert line[2:].strip()
