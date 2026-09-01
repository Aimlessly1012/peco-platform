"""需求功能思维导图单测（M6 B2/B3）。

功能点提取的价值全在"输出是业务语言而不是技术语言"，所以解析层的过滤规则
（技术词、路径、超长、纯英文标识符）是重点覆盖对象。
"""
import pytest

from app.services.report.features import (
    MAX_POINT_CHARS,
    build_feature_map,
    domain_titles,
    extract_module_features,
    feature_domains,
    generate_feature_map,
    parse_feature_points,
    project_tagline,
    route_segment_points,
)
from app.services.report.graph_reader import FileNode, ModuleNode, ProjectTree
from tests.helpers.report import FakeLLM, make_tree

ANCHORS = {
    "api:orders": [
        "backend/routers/orders.py（create_order, list_orders）",
        "backend/services/order_service.py（save_order）",
    ],
    "page:orders": [
        "frontend/pages/orders.tsx（OrdersPage）",
        "frontend/components/OrderCard.tsx（OrderCard）",
    ],
    "api:users": ["backend/routers/users.py（get_user）"],
}


# ---------------- 输出解析与质量闸门 ----------------


def test_parse_normal_output():
    raw = "- 创建订单\n- 查询订单列表\n- 取消订单"
    assert parse_feature_points(raw) == ["创建订单", "查询订单列表", "取消订单"]


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("1. 创建订单\n2. 取消订单", ["创建订单", "取消订单"]),
        ("* 创建订单\n+ 取消订单", ["创建订单", "取消订单"]),
        ("创建订单\n取消订单", ["创建订单", "取消订单"]),
        ("- 创建订单（含草稿）", ["创建订单"]),          # 去掉尾部括号补充
        ("- 创建订单\n\n- 创建订单", ["创建订单"]),        # 去重
    ],
)
def test_parse_tolerates_format_variants(raw, expect):
    assert parse_feature_points(raw) == expect


@pytest.mark.parametrize(
    "line",
    [
        "- 渲染订单列表组件",     # 技术词：组件
        "- 封装订单接口",         # 技术词：接口/封装
        "- 提供订单 API",         # 技术词：API
        "- 修改 orders.py 文件",  # 技术词 + 路径
        "- OrdersPage",           # 纯英文标识符
        "- frontend/pages/orders.tsx",  # 路径
        "- 这是一条明显超过十四个字上限的功能点描述",  # 超长
        "-",                      # 空
    ],
)
def test_parse_rejects_technical_or_invalid_lines(line):
    assert parse_feature_points(line) == []


def test_parse_caps_at_six_points():
    raw = "\n".join(f"- 功能{i}" for i in range(20))
    assert len(parse_feature_points(raw)) == 6


def test_parse_keeps_valid_and_drops_invalid_in_same_output():
    raw = "- 创建订单\n- 渲染订单组件\n- 导出结算单"
    assert parse_feature_points(raw) == ["创建订单", "导出结算单"]


def test_all_points_within_char_limit():
    raw = "- 创建订单\n- 按模板批量创建广告任务计划"
    for point in parse_feature_points(raw):
        assert len(point) <= MAX_POINT_CHARS


# ---------------- 提取：成功 / 重试 / 降级 / 缓存 ----------------


def orders_api() -> ModuleNode:
    tree = make_tree()
    module = next(m for m in tree.modules if m.key == "api:orders")
    module.agg_hash = "hash-orders"
    return module


async def test_extract_returns_llm_points():
    llm = FakeLLM(feature_returns="- 创建订单\n- 查询订单列表")
    points, source = await extract_module_features(orders_api(), ANCHORS["api:orders"], llm)

    assert points == ["创建订单", "查询订单列表"]
    assert source == "llm"
    assert len(llm.feature_calls) == 1


async def test_extract_prompt_is_anchored_on_real_entries():
    """防幻觉的关键：prompt 里的入口清单必须是图里的真实路径与函数名。"""
    llm = FakeLLM()
    await extract_module_features(orders_api(), ANCHORS["api:orders"], llm)

    call = llm.feature_calls[0]
    assert "backend/routers/orders.py" in call["anchors"]
    assert "create_order" in call["anchors"]
    assert call["name"] == "orders"
    assert call["kind_label"] == "接口"
    assert call["prefix"] == "/api/orders"
    assert "订单接口模块" in call["summary"]


async def test_extract_retries_once_then_succeeds():
    llm = FakeLLM(feature_returns=["- 渲染组件", "- 创建订单\n- 取消订单"])
    points, source = await extract_module_features(orders_api(), ANCHORS["api:orders"], llm)

    assert points == ["创建订单", "取消订单"]
    assert source == "llm"
    assert len(llm.feature_calls) == 2


@pytest.mark.parametrize(
    "returns",
    [
        ["- 渲染组件", "- 封装接口"],                    # 两次都被质量闸门拒绝
        [None, None],                                     # 两次都空
        [RuntimeError("超时"), RuntimeError("超时")],     # 两次都异常
    ],
)
async def test_extract_falls_back_after_two_failures(returns):
    """spec 场景: 两次失败 → 降级为入口清单，不抛异常。"""
    llm = FakeLLM(feature_returns=returns)
    points, source = await extract_module_features(orders_api(), ANCHORS["api:orders"], llm)

    assert source == "fallback"
    assert points == ["orders", "order_service"]   # 路径段，不编造业务语义
    assert len(llm.feature_calls) == 2


async def test_extract_uses_cache_without_calling_llm():
    llm = FakeLLM()
    cache = {"hash-orders": ["创建订单", "取消订单"]}

    points, source = await extract_module_features(
        orders_api(), ANCHORS["api:orders"], llm, cache
    )

    assert points == ["创建订单", "取消订单"]
    assert source == "cache"
    assert llm.feature_calls == []


async def test_extract_accepts_single_point():
    """单一职责的模块（如健康检查）只该有 1 条功能点——不能因"条数少"判失败降级。"""
    llm = FakeLLM(feature_returns="- 执行健康检查")
    points, source = await extract_module_features(orders_api(), ANCHORS["api:orders"], llm)

    assert points == ["执行健康检查"]
    assert source == "llm"
    assert len(llm.feature_calls) == 1   # 不该触发重试


async def test_extract_cache_miss_on_different_hash():
    module = orders_api()
    module.agg_hash = "changed-hash"
    llm = FakeLLM(feature_returns="- 创建订单\n- 取消订单")

    _, source = await extract_module_features(
        module, ANCHORS["api:orders"], llm, {"hash-orders": ["旧的"]}
    )
    assert source == "llm"


def test_route_segment_points_prefers_meaningful_names():
    module = ModuleNode(key="page:orders", name="orders", kind="page", files=[])
    points = route_segment_points(
        module,
        ["src/pages/orders/index.tsx（OrdersPage）", "src/pages/orders/[id].tsx", "src/pages/orders/new.tsx"],
    )
    # index 用其父目录名，动态段去掉方括号
    assert points == ["orders", "id", "new"]


# ---------------- 功能域选择与命名 ----------------


def test_shared_module_excluded():
    """D4: shared 不是用户功能，不入功能导图。"""
    keys = [m.key for m in feature_domains(make_tree())]
    assert "shared:shared" not in keys
    assert set(keys) == {"api:orders", "page:orders", "api:users"}


def test_page_before_api_and_bigger_first():
    domains = feature_domains(make_tree())
    assert domains[0].kind == "page"          # 前台功能在前
    assert [m.key for m in domains] == ["page:orders", "api:orders", "api:users"]


def test_dir_modules_included_as_domains():
    tree = ProjectTree(
        project_id="p", name="x",
        modules=[ModuleNode(key="dir:src", name="src", kind="dir", files=[FileNode(path="src/a.ts")])],
    )
    assert [m.key for m in feature_domains(tree)] == ["dir:src"]


def test_duplicate_names_get_kind_suffix():
    """D4: page 与 api 同名功能域并列时加类型后缀区分。"""
    titles = domain_titles(feature_domains(make_tree()))

    assert titles["page:orders"] == "orders（页面）"
    assert titles["api:orders"] == "orders（接口）"
    assert titles["api:users"] == "users"      # 不重名的不加后缀


# ---------------- 产品定位与拼装 ----------------


@pytest.mark.parametrize(
    "summary,expect",
    [
        ("项目定位：面向广告主的投放管理平台\n技术栈：umi", "面向广告主的投放管理平台"),
        ("这是一个订单管理系统。技术栈是 FastAPI", "这是一个订单管理系统"),
        ("", "代码仓库功能概览"),
    ],
)
def test_project_tagline(summary, expect):
    tree = ProjectTree(project_id="p", name="x", summary=summary)
    assert project_tagline(tree) == expect


def test_build_feature_map_three_levels():
    """M6 spec: 三层结构 产品定位 → 功能域 → 功能点。"""
    tree = make_tree()
    markdown = build_feature_map(
        tree,
        {
            "page:orders": ["浏览订单列表", "查看订单详情"],
            "api:orders": ["创建订单", "取消订单"],
            "api:users": ["查询用户资料"],
        },
    )
    lines = markdown.splitlines()

    assert lines[0].startswith("# mini-shop：")
    assert markdown.count("\n## ") == 3           # 三个功能域
    assert "## orders（页面）" in markdown
    assert "- 浏览订单列表" in markdown
    assert "shared" not in markdown               # shared 不入图
    # 层级顺序：功能点紧跟在它的功能域之后
    page_index = lines.index("## orders（页面）")
    assert lines[page_index + 1] == "- 浏览订单列表"


def test_build_feature_map_marks_empty_domain():
    markdown = build_feature_map(make_tree(), {})
    assert "（暂未提取到功能点）" in markdown


def test_build_feature_map_without_domains():
    tree = ProjectTree(
        project_id="p", name="lib-only",
        modules=[ModuleNode(key="shared:shared", name="shared", kind="shared")],
    )
    markdown = build_feature_map(tree, {})
    assert markdown.startswith("# lib-only：")
    assert "暂未识别到用户功能模块" in markdown


def test_feature_map_is_valid_markdown_hierarchy():
    """markmap 靠 #/##/- 的层级吃 markdown，不能出现跳级或空标题。"""
    markdown = build_feature_map(make_tree(), {"page:orders": ["浏览订单列表"]})
    for line in markdown.splitlines():
        if line.startswith("#"):
            assert line.lstrip("#").startswith(" ")
            assert line.lstrip("# ").strip()
        elif line.startswith("-"):
            assert line[2:].strip()


# ---------------- 端到端编排 ----------------


async def test_generate_feature_map_deep():
    llm = FakeLLM(
        feature_returns={
            "orders": "- 创建订单\n- 查询订单列表",
            "users": "- 查询用户资料\n- 修改用户信息",
        }
    )
    markdown, cacheable, stats = await generate_feature_map(make_tree(), ANCHORS, llm)

    assert stats["feature_domains"] == 3
    assert stats["feature_points_new"] == 3
    assert stats["feature_points_fallback"] == 0
    assert "- 创建订单" in markdown
    assert "- 查询用户资料" in markdown
    assert len(llm.feature_calls) == 3           # 每个功能域一次小调用


async def test_generate_feature_map_single_module_failure_does_not_break_others():
    """spec 场景: 某模块提取失败只降级该功能域，其余正常。"""
    tree = make_tree()
    for module in tree.modules:
        module.agg_hash = f"hash-{module.key}"
    llm = FakeLLM(
        feature_returns={
            "orders": "- 创建订单\n- 查询订单列表",
            "users": None,                        # users 两次都拿不到
        }
    )

    markdown, cacheable, stats = await generate_feature_map(tree, ANCHORS, llm)

    assert stats["feature_points_new"] == 2
    assert stats["feature_points_fallback"] == 1
    assert "- 创建订单" in markdown               # 其余功能域正常
    assert "## users" in markdown                 # 失败的功能域仍在图里
    assert "- users" in markdown                  # 降级为入口清单
    # 降级结果不进缓存，下次重索引还会重试
    assert all("hash-api:users" != h for h in cacheable)


async def test_generate_feature_map_caches_only_llm_results():
    tree = make_tree()
    for module in tree.modules:
        module.agg_hash = f"hash-{module.key}"
    llm = FakeLLM(feature_returns={"orders": "- 创建订单\n- 取消订单", "users": None})

    _, cacheable, _ = await generate_feature_map(tree, ANCHORS, llm)

    assert set(cacheable) == {"hash-page:orders", "hash-api:orders"}
    assert cacheable["hash-api:orders"] == ["创建订单", "取消订单"]


async def test_generate_feature_map_fast_is_programmatic():
    """spec: fast 模式零 LLM，功能点为入口清单。"""
    llm = FakeLLM()
    markdown, cacheable, stats = await generate_feature_map(
        make_tree(), ANCHORS, llm, fast=True
    )

    assert llm.feature_calls == []
    assert cacheable == {}
    assert stats["feature_points_new"] == 0
    assert stats["feature_domains"] == 3
    assert "## orders（页面）" in markdown
    assert "- orders" in markdown


async def test_generate_feature_map_dir_modules_skip_llm():
    """D4: dir 降级模块程序化，不花 LLM。"""
    tree = ProjectTree(
        project_id="p", name="x", summary="项目定位：工具集",
        modules=[
            ModuleNode(key="dir:scripts", name="scripts", kind="dir",
                       files=[FileNode(path="scripts/build.ts")]),
        ],
    )
    llm = FakeLLM()
    markdown, _, stats = await generate_feature_map(
        tree, {"dir:scripts": ["scripts/build.ts（run）"]}, llm
    )

    assert llm.feature_calls == []
    assert stats["feature_points_fallback"] == 1
    assert "## scripts" in markdown
    assert "- build" in markdown
