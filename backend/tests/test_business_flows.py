"""业务流程图单测（M6 B5）：flowchart 校验、多图解析、锚点提取与降级。

需求方向而非代码方向——校验的重点是"节点是业务步骤"与"图不失控"。
"""
import pytest

from app.services.report.flows import (
    MAX_FLOWS,
    fallback_flows,
    generate_business_flows,
    module_flow_lines,
    parse_business_flows,
    project_flow_lines,
    validate_flows,
)
from app.services.report.graph_reader import FileNode, ModuleNode, ProjectTree
from app.services.report.mermaid_check import validate_flowchart
from tests.helpers.report import GOOD_FLOW_OUTPUT, FakeLLM

GOOD_FLOW = """flowchart TD
    A[用户选择商品] --> B[提交订单]
    B --> C{是否有库存}
    C -->|有| D[生成订单]
    C -->|无| E[提示缺货]"""


def flow_tree() -> ProjectTree:
    return ProjectTree(
        project_id="p1", name="mini-shop",
        summary=(
            "项目定位：一个订单管理系统\n"
            "技术栈：FastAPI + React\n"
            "架构风格：前后端分离\n"
            "核心业务流：\n"
            "- 用户下单并支付\n"
            "- 商家发货与用户收货"
        ),
        modules=[
            ModuleNode(
                key="api:orders", name="orders", kind="api", route_prefix="/api/orders",
                summary=(
                    "业务目标：处理订单\n"
                    "关键流程：\n"
                    "- 前端提交订单数据\n"
                    "- 服务层校验库存并落库\n"
                    "核心文件：orders.py"
                ),
                files=[FileNode(path="backend/routers/orders.py")],
            ),
            ModuleNode(
                key="shared:shared", name="shared", kind="shared",
                summary="关键流程：\n- 不该出现在业务流输入里",
                files=[FileNode(path="backend/models.py")],
            ),
        ],
    )


# ---------------- flowchart 校验器 ----------------


def test_validate_good_flowchart():
    assert validate_flowchart(GOOD_FLOW) == (True, "")


@pytest.mark.parametrize(
    "header", ["flowchart TD", "flowchart LR", "graph TD", "flowchart BT"]
)
def test_validate_accepts_header_variants(header):
    assert validate_flowchart(f"{header}\n    A[开始] --> B[结束]")[0] is True


def test_validate_accepts_fenced_and_keywords():
    fenced = f"```mermaid\n{GOOD_FLOW}\n```"
    assert validate_flowchart(fenced)[0] is True

    with_style = """flowchart TD
    A[提交申请] --> B[审批]
    classDef done fill:#eee
    class B done"""
    assert validate_flowchart(with_style) == (True, "")


@pytest.mark.parametrize(
    "text,keyword",
    [
        ("", "空"),
        ("sequenceDiagram\n    A->>B: x", "flowchart"),
        ("flowchart TD\n    这里是一段解释说明文字", "无法识别的行"),
        ("flowchart TD\n    A[只有一个节点]", "没有任何连线"),
        ("flowchart TD\n    A --> A", "节点不足"),
    ],
)
def test_validate_rejects_bad_flowchart(text, keyword):
    ok, reason = validate_flowchart(text)
    assert ok is False
    assert keyword in reason


def test_validate_rejects_too_many_nodes():
    """一张图讲一条流：节点超上限说明画成了网。"""
    lines = ["flowchart TD"] + [f"    N{i}[步骤{i}] --> N{i + 1}[步骤{i + 1}]" for i in range(10)]
    ok, reason = validate_flowchart("\n".join(lines))

    assert ok is False
    assert "超过上限" in reason


def test_validate_counts_unique_nodes_not_lines():
    """同一节点重复出现在多条边里不该被算成多个节点。"""
    text = """flowchart TD
    A[开始] --> B[校验]
    A --> C[记录]
    B --> D[结束]
    C --> D"""
    assert validate_flowchart(text) == (True, "")


# ---------------- 多图解析 ----------------


def test_parse_multiple_flows():
    flows = parse_business_flows(GOOD_FLOW_OUTPUT)

    assert [f["title"] for f in flows] == ["下单流程", "取消流程"]
    assert flows[0]["mermaid"].startswith("flowchart TD")
    assert "```" not in flows[0]["mermaid"]


def test_parse_caps_flow_count():
    sections = "\n\n".join(
        f"## 流程{i}\n```mermaid\nflowchart TD\n    A[甲] --> B[乙]\n```" for i in range(8)
    )
    assert len(parse_business_flows(sections)) == MAX_FLOWS


def test_parse_truncates_long_title():
    raw = "## 这是一个非常长的业务流程标题超过限制\n```mermaid\nflowchart TD\n    A[甲] --> B[乙]\n```"
    assert len(parse_business_flows(raw)[0]["title"]) <= 12


def test_parse_bare_flowchart_without_title():
    """模型偶尔省略标题只给一张图，也要认。"""
    flows = parse_business_flows(f"```mermaid\n{GOOD_FLOW}\n```")

    assert len(flows) == 1
    assert flows[0]["title"] == "核心业务流"
    assert flows[0]["mermaid"].startswith("flowchart TD")


def test_parse_ignores_section_without_diagram():
    raw = "## 只有标题没有图\n\n## 下单流程\n```mermaid\nflowchart TD\n    A[甲] --> B[乙]\n```"
    flows = parse_business_flows(raw)

    assert [f["title"] for f in flows] == ["下单流程"]


def test_parse_empty():
    assert parse_business_flows("") == []
    assert parse_business_flows("完全没有图的一段话") == []


def test_validate_flows_keeps_valid_drops_invalid():
    """一张不合格不该拖垮其他张。"""
    flows = [
        {"title": "好流程", "mermaid": GOOD_FLOW},
        {"title": "坏流程", "mermaid": "flowchart TD\n    这是散文"},
    ]
    valid, reason = validate_flows(flows)

    assert [f["title"] for f in valid] == ["好流程"]
    assert "坏流程" in reason


# ---------------- 输入锚点提取 ----------------


def test_project_flow_lines_from_l4():
    assert project_flow_lines(flow_tree()) == ["用户下单并支付", "商家发货与用户收货"]


def test_project_flow_lines_inline_format():
    tree = ProjectTree(project_id="p", name="x", summary="核心业务流：用户下单并支付")
    assert project_flow_lines(tree) == ["用户下单并支付"]


def test_project_flow_lines_fallback_to_whole_summary():
    tree = ProjectTree(project_id="p", name="x", summary="一个没有分节的总览")
    assert project_flow_lines(tree) == ["一个没有分节的总览"]


def test_project_flow_lines_empty_summary():
    assert project_flow_lines(ProjectTree(project_id="p", name="x")) == []


def test_module_flow_lines_only_feature_kinds():
    lines = module_flow_lines(flow_tree())

    assert len(lines) == 1
    assert lines[0].startswith("- orders：")
    assert "前端提交订单数据" in lines[0]
    assert "不该出现" not in "\n".join(lines)   # shared 不进业务流输入


def test_section_extraction_stops_at_next_heading():
    """「关键流程」后面跟着「核心文件」，不能把文件名混进流程步骤。"""
    lines = module_flow_lines(flow_tree())
    assert "orders.py" not in lines[0]


# ---------------- 生成：成功 / 重试 / 降级 ----------------


async def test_generate_business_flows_success():
    llm = FakeLLM()
    flows, stats = await generate_business_flows(flow_tree(), llm)

    assert stats == {"business_flows_ok": 2, "business_flows_fallback": 0}
    assert [f["title"] for f in flows] == ["下单流程", "取消流程"]
    assert all(f["mermaid"].startswith("flowchart TD") for f in flows)
    assert all(f["fallback_text"] == "" for f in flows)
    assert len(llm.flow_calls) == 1


async def test_generate_passes_business_anchors_to_prompt():
    llm = FakeLLM()
    await generate_business_flows(flow_tree(), llm)

    call = llm.flow_calls[0]
    assert "用户下单并支付" in call["flow_lines"]
    assert "orders" in call["module_flows"]
    assert call["retry_reason"] == ""


async def test_generate_retries_once_then_succeeds():
    llm = FakeLLM(flow_returns=["## 坏图\n```mermaid\nflowchart TD\n这是散文\n```", GOOD_FLOW_OUTPUT])
    flows, stats = await generate_business_flows(flow_tree(), llm)

    assert stats["business_flows_ok"] == 2
    assert len(llm.flow_calls) == 2
    assert llm.flow_calls[1]["retry_reason"]      # 重试时带上失败原因


@pytest.mark.parametrize(
    "returns",
    [
        ["## 坏图\n```mermaid\nflowchart TD\n散文一段\n```"] * 2,
        [None, None],
        [RuntimeError("超时"), RuntimeError("超时")],
        ["完全没有图的回答"] * 2,
    ],
)
async def test_generate_falls_back_to_text(returns):
    """spec: 两次失败 → fallback_text 存业务流原文，不抛异常。"""
    llm = FakeLLM(flow_returns=returns)
    flows, stats = await generate_business_flows(flow_tree(), llm)

    assert stats == {"business_flows_ok": 0, "business_flows_fallback": 1}
    assert flows[0]["mermaid"] == ""
    assert "用户下单并支付" in flows[0]["fallback_text"]
    assert len(llm.flow_calls) == 2               # 只重试 1 次


async def test_generate_skips_when_no_business_flow_in_summary():
    """L4 里没有业务流信息时不调 LLM。"""
    llm = FakeLLM()
    tree = ProjectTree(project_id="p", name="x", summary="")

    flows, stats = await generate_business_flows(tree, llm)

    assert flows == []
    assert stats == {"business_flows_ok": 0, "business_flows_fallback": 0}
    assert llm.flow_calls == []


def test_fallback_flows_numbers_the_lines():
    flows = fallback_flows(flow_tree())
    assert flows[0]["fallback_text"] == "1. 用户下单并支付\n2. 商家发货与用户收货"
