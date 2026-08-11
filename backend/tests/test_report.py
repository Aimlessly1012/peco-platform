"""M3 报告生成单测（B2/B3）：思维导图程序化生成、mermaid 启发式校验、降级路径。

LLM 全部用 mock（FakeLLM），不触网；图数据用手写 dataclass，不依赖 Neo4j。
"""
import pytest

from app.services.report.builder import (
    build_fallback_text,
    build_module_context,
    build_module_lines,
    fallback_doc,
    generate_doc,
    generate_one_sequence,
    generate_sequences,
    select_core_modules,
)
from app.services.report.graph_reader import (
    ApiEdgeInfo,
    FileNode,
    GraphEdges,
    ImportEdgeInfo,
    ModuleNode,
    ProjectTree,
)
from app.services.report.mermaid_check import (
    split_arrow,
    strip_fence,
    validate_mindmap,
    validate_sequence,
)
from app.services.report.mindmap import build_mindmap, escape_node_text

GOOD_SEQ = """sequenceDiagram
    participant U as 用户
    participant FE as 订单页面
    participant BE as 订单接口
    U->>FE: 打开订单列表
    FE->>BE: GET /api/orders
    BE-->>FE: 返回订单数组
    FE-->>U: 渲染列表"""


def make_tree() -> ProjectTree:
    """两个核心模块（api/page，文件≥2）+ 一个单文件模块 + 一个 shared 模块。"""
    return ProjectTree(
        project_id="p1",
        name="mini-shop",
        summary="全栈演示项目：订单与用户",
        modules=[
            ModuleNode(
                key="api:orders", name="orders", kind="api", route_prefix="/api/orders",
                summary="订单接口模块：创建与查询订单",
                files=[
                    FileNode(path="backend/routers/orders.py", language="python", summary="订单路由"),
                    FileNode(path="backend/services/order_service.py", language="python", summary="订单服务"),
                ],
            ),
            ModuleNode(
                key="page:orders", name="orders", kind="page", route_prefix="/orders",
                summary="订单页面模块",
                files=[
                    FileNode(path="frontend/pages/orders.tsx", language="typescript", summary="订单页"),
                    FileNode(path="frontend/components/OrderCard.tsx", language="typescript", summary="订单卡片"),
                    FileNode(path="frontend/lib/api.ts", language="typescript", summary="接口封装"),
                ],
            ),
            ModuleNode(
                key="api:users", name="users", kind="api", route_prefix="/api/users",
                summary="用户接口模块",
                files=[FileNode(path="backend/routers/users.py", language="python", summary="用户路由")],
            ),
            ModuleNode(
                key="shared:shared", name="shared", kind="shared",
                files=[FileNode(path="backend/models.py", language="python", summary="数据模型")],
            ),
        ],
    )


def make_edges() -> GraphEdges:
    return GraphEdges(
        api_edges=[
            ApiEdgeInfo(
                src_file="frontend/lib/api.ts", src_symbol="apiGet", src_start=10,
                dst_file="backend/routers/orders.py", dst_symbol="list_orders", dst_start=20,
            ),
            ApiEdgeInfo(
                src_file="frontend/pages/orders.tsx", src_symbol="OrdersPage", src_start=5,
                dst_file="backend/routers/orders.py", dst_symbol="create_order", dst_start=40,
            ),
        ],
        import_edges=[
            ImportEdgeInfo(src="backend/routers/orders.py", dst="backend/services/order_service.py"),
            ImportEdgeInfo(src="frontend/pages/orders.tsx", dst="frontend/lib/api.ts"),
            ImportEdgeInfo(src="frontend/pages/orders.tsx", dst="frontend/components/OrderCard.tsx"),
        ],
    )


class FakeLLM:
    """可编程假 LLM：doc_returns / seq_returns 支持值、None 与异常实例。"""

    def __init__(self, doc_returns=None, seq_returns=None):
        self.doc_returns = doc_returns
        self.seq_returns = list(seq_returns or [])
        self.doc_calls: list[tuple] = []
        self.seq_calls: list[dict] = []

    async def generate_doc(self, project_name, overview, module_lines, module_summaries):
        self.doc_calls.append((project_name, overview, module_lines, module_summaries))
        if isinstance(self.doc_returns, Exception):
            raise self.doc_returns
        return self.doc_returns

    async def generate_sequence(
        self, name, kind, prefix, summary, entry_summaries,
        api_lines, import_lines, retry_reason="",
    ):
        self.seq_calls.append({"name": name, "retry_reason": retry_reason})
        if not self.seq_returns:
            return None
        value = self.seq_returns.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


# ---------------- 思维导图（B2，程序化生成） ----------------


def test_mindmap_structure_matches_graph():
    """spec: mindmap 模块与文件层级与图结构一致，不含图中不存在的名称。"""
    tree = make_tree()
    out = build_mindmap(tree)
    lines = out.splitlines()

    assert lines[0] == "mindmap"
    assert lines[1] == '  root(("mini-shop"))'

    # 每个模块一行（缩进 4）、每个文件一行（缩进 6），层级严格递进
    module_lines = [ln for ln in lines if ln.startswith("    ") and not ln.startswith("      ")]
    file_lines = [ln for ln in lines if ln.startswith("      ")]
    assert len(module_lines) == len(tree.modules)
    assert len(file_lines) == sum(len(m.files) for m in tree.modules)

    # 不含图中不存在的名称：文件行文本必须是图里的真实路径
    graph_paths = {f.path for m in tree.modules for f in m.files}
    for ln in file_lines:
        text = ln.split('["', 1)[1].rsplit('"]', 1)[0]
        assert text in graph_paths, f"mindmap 出现图中不存在的文件：{text}"
    for m in tree.modules:
        assert m.name in out


def test_mindmap_module_label_carries_kind_and_prefix():
    out = build_mindmap(make_tree())
    assert "[接口] orders /api/orders" in out
    assert "[页面] orders /orders" in out
    assert "[共享] shared" in out


def test_mindmap_is_valid_by_self_check():
    assert validate_mindmap(build_mindmap(make_tree())) == (True, "")


def test_mindmap_empty_modules():
    tree = ProjectTree(project_id="p1", name="空项目")
    out = build_mindmap(tree)
    assert out.startswith("mindmap")
    assert "暂无模块数据" in out
    assert validate_mindmap(out)[0] is True


def test_mindmap_truncates_file_list():
    tree = ProjectTree(
        project_id="p1", name="big",
        modules=[
            ModuleNode(
                key="api:big", name="big", kind="api",
                files=[FileNode(path=f"src/f{i}.py") for i in range(15)],
            )
        ],
    )
    out = build_mindmap(tree, max_files=12)
    assert "… 其余 3 个文件" in out
    assert "src/f12.py" not in out


@pytest.mark.parametrize(
    "raw,expect_absent",
    [
        ('模块 "订单"', '"'),
        ("含`反引号`的名字", "`"),
        ("跨\n行\n文本", "\n"),
    ],
)
def test_escape_node_text_removes_breaking_chars(raw, expect_absent):
    assert expect_absent not in escape_node_text(raw)


def test_escape_node_text_truncates_and_defaults():
    assert len(escape_node_text("x" * 200)) == 80
    assert escape_node_text("   ") == "(未命名)"


def test_mindmap_escapes_quotes_in_module_name():
    tree = ProjectTree(
        project_id="p1", name='项目"名"',
        modules=[ModuleNode(key='api:a"b', name='a"b', kind="api", files=[])],
    )
    out = build_mindmap(tree)
    # 节点文本一律用 id["..."] 包裹，内部不得再出现裸双引号（否则前端解析炸）
    for line in out.splitlines()[1:]:
        inner = line.split('["', 1)[-1].rsplit('"]', 1)[0] if '["' in line else ""
        assert '"' not in inner


# ---------------- mermaid 启发式校验（B3/D2） ----------------


def test_validate_sequence_accepts_good():
    assert validate_sequence(GOOD_SEQ) == (True, "")


def test_validate_sequence_accepts_fenced_and_keywords():
    fenced = f"```mermaid\n{GOOD_SEQ}\n```"
    assert validate_sequence(fenced)[0] is True

    with_keywords = """sequenceDiagram
    autonumber
    participant FE as 前端
    participant BE as 后端
    Note over FE,BE: 登录流程
    loop 每 30 秒
        FE->>BE: GET /api/status
        BE-->>FE: 200 OK
    end"""
    assert validate_sequence(with_keywords) == (True, "")


@pytest.mark.parametrize(
    "text,keyword",
    [
        ("", "空"),
        ("graph TD\n  A-->B", "sequenceDiagram"),
        ("sequenceDiagram\n    participant\n    A->>B: x", "参与者行格式非法"),
        ("sequenceDiagram\n    participant A as 甲\n    participant B as 乙", "消息箭头"),
        ("sequenceDiagram\n    这是一段解释说明文字\n    A->>B: x", "无法识别的行"),
        ("sequenceDiagram\n    A->>A: 自己调自己", "参与者不足"),
    ],
)
def test_validate_sequence_rejects_bad(text, keyword):
    ok, reason = validate_sequence(text)
    assert ok is False
    assert keyword in reason


def test_strip_fence_variants():
    assert strip_fence("```mermaid\nsequenceDiagram\n```") == "sequenceDiagram"
    assert strip_fence("```\nabc\n```") == "abc"
    assert strip_fence("sequenceDiagram\n  A->>B: x").startswith("sequenceDiagram")
    assert strip_fence("") == ""
    # 带前导说明的输出仍能取出图源码
    assert strip_fence("时序图如下：\n```mermaid\nsequenceDiagram\n```") == "sequenceDiagram"


def test_strip_fence_keeps_inner_code_blocks():
    """整篇文档被 ```markdown 包裹且内部含代码块时，只剥外层、不截断正文。"""
    doc = "```markdown\n# 标题\n\n```python\nprint(1)\n```\n\n## 尾节\n```"
    out = strip_fence(doc)
    assert out.startswith("# 标题")
    assert "```python" in out
    assert "## 尾节" in out


def test_split_arrow_forms():
    assert split_arrow("FE->>BE: 请求") == ("FE", "BE", "请求")
    assert split_arrow("BE-->>FE: 返回") == ("BE", "FE", "返回")
    assert split_arrow("FE->>+BE: 激活") == ("FE", "BE", "激活")
    assert split_arrow("Note over A,B: 说明") is None
    assert split_arrow("participant A as 甲") is None


# ---------------- 核心模块筛选与上下文（B3） ----------------


def test_select_core_modules_rule():
    """spec: kind 为 api/page 且 CONTAINS 文件数 ≥2，按文件数降序，上限 6。"""
    picked = select_core_modules(make_tree())
    keys = [m.key for m in picked]
    assert keys == ["page:orders", "api:orders"]  # 3 文件在前，2 文件在后
    assert "api:users" not in keys  # 单文件被排除
    assert "shared:shared" not in keys  # kind 不合格


def test_select_core_modules_limit():
    tree = ProjectTree(
        project_id="p1",
        modules=[
            ModuleNode(
                key=f"api:m{i}", name=f"m{i}", kind="api",
                files=[FileNode(path=f"a{i}.py"), FileNode(path=f"b{i}.py")],
            )
            for i in range(10)
        ],
    )
    assert len(select_core_modules(tree)) == 6


def test_build_module_context_filters_edges_and_ranks_entries():
    tree = make_tree()
    mod = next(m for m in tree.modules if m.key == "api:orders")
    ctx = build_module_context(mod, make_edges())

    # 只保留与本模块文件相关的边
    assert len(ctx.api_lines) == 2
    assert all("orders.py" in line for line in ctx.api_lines)
    assert ctx.import_lines == ["backend/routers/orders.py → backend/services/order_service.py"]

    # 参与 CALLS_API 的文件优先作为入口
    assert ctx.entry_files[0].path == "backend/routers/orders.py"
    assert "backend/routers/orders.py：订单路由" in ctx.entry_summaries


def test_build_fallback_text_lists_links():
    tree = make_tree()
    mod = next(m for m in tree.modules if m.key == "api:orders")
    text = build_fallback_text(build_module_context(mod, make_edges()))
    assert "前后端调用：" in text
    assert "文件依赖：" in text
    assert "list_orders" in text


def test_build_fallback_text_without_edges_uses_files():
    mod = ModuleNode(
        key="api:solo", name="solo", kind="api",
        files=[FileNode(path="a.py", summary="甲")],
    )
    text = build_fallback_text(build_module_context(mod, GraphEdges()))
    assert "核心文件：" in text
    assert "a.py：甲" in text


def test_build_module_lines_covers_all_modules():
    lines = build_module_lines(make_tree())
    assert lines.count("\n") == len(make_tree().modules) - 1
    assert "[api] orders（路由 /api/orders，2 个文件）" in lines


# ---------------- 需求逻辑文档：正常与降级（B3） ----------------


async def test_generate_doc_uses_llm_output():
    llm = FakeLLM(doc_returns="# 文档\n正文内容")
    doc, fallback = await generate_doc(make_tree(), llm)
    assert fallback is False
    assert doc == "# 文档\n正文内容"
    assert llm.doc_calls[0][0] == "mini-shop"


async def test_generate_doc_strips_wrapping_fence():
    llm = FakeLLM(doc_returns="```markdown\n# 文档\n正文\n```")
    doc, fallback = await generate_doc(make_tree(), llm)
    assert fallback is False
    assert doc.startswith("# 文档")
    assert "```" not in doc


@pytest.mark.parametrize("bad", [None, "", "   ", RuntimeError("上游 500")])
async def test_generate_doc_falls_back(bad):
    """spec: 文档生成失败降级为 L4+L3 原文拼接。"""
    doc, fallback = await generate_doc(make_tree(), FakeLLM(doc_returns=bad))
    assert fallback is True
    assert doc.startswith("# mini-shop 需求逻辑文档")
    assert "全栈演示项目：订单与用户" in doc      # L4
    assert "订单接口模块：创建与查询订单" in doc  # L3
    assert "backend/routers/orders.py" in doc     # 关键文件


def test_fallback_doc_is_readable_markdown():
    doc = fallback_doc(make_tree())
    assert doc.count("\n### ") == len(make_tree().modules)
    assert "## 一、系统概述" in doc


# ---------------- 时序图：校验、重试、降级（B3） ----------------


async def test_generate_one_sequence_success_first_try():
    tree = make_tree()
    mod = next(m for m in tree.modules if m.key == "api:orders")
    llm = FakeLLM(seq_returns=[GOOD_SEQ])
    item = await generate_one_sequence(build_module_context(mod, make_edges()), llm)

    assert item["mermaid"].startswith("sequenceDiagram")
    assert item["module_key"] == "api:orders"
    assert item["module_name"] == "orders"
    assert item["fallback_text"]  # 降级文本始终备好
    assert len(llm.seq_calls) == 1


async def test_generate_one_sequence_retries_once_then_succeeds():
    """spec: 校验失败自动重试 1 次，重试提示带上失败原因。"""
    tree = make_tree()
    mod = next(m for m in tree.modules if m.key == "api:orders")
    llm = FakeLLM(seq_returns=["graph TD\n A-->B", GOOD_SEQ])
    item = await generate_one_sequence(build_module_context(mod, make_edges()), llm)

    assert item["mermaid"].startswith("sequenceDiagram")
    assert len(llm.seq_calls) == 2
    assert llm.seq_calls[0]["retry_reason"] == ""
    assert "sequenceDiagram" in llm.seq_calls[1]["retry_reason"]


@pytest.mark.parametrize(
    "returns",
    [
        ["graph TD\n A-->B", "还是不对的散文"],           # 两次都不合法
        [None, None],                                      # 两次都空
        [RuntimeError("timeout"), RuntimeError("timeout")],  # 两次都抛异常
    ],
)
async def test_generate_one_sequence_falls_back_after_two_failures(returns):
    tree = make_tree()
    mod = next(m for m in tree.modules if m.key == "api:orders")
    llm = FakeLLM(seq_returns=returns)
    item = await generate_one_sequence(build_module_context(mod, make_edges()), llm)

    assert item["mermaid"] == ""
    assert "调用链路" in item["fallback_text"]
    assert len(llm.seq_calls) == 2  # 只重试 1 次，不无限重试


async def test_generate_sequences_isolates_failures():
    """spec 场景: 某模块两次均失败 → 该模块 fallback_text，其余模块正常。"""
    tree = make_tree()
    # 顺序：page:orders(3 文件) 先，api:orders 后；gather 并发但取值顺序固定
    llm = FakeLLM(seq_returns=[GOOD_SEQ, "非法内容", "仍然非法"])
    sequences, ok, fallback = await generate_sequences(tree, make_edges(), llm)

    assert len(sequences) == 2
    assert (ok, fallback) == (1, 1)
    good = [s for s in sequences if s["mermaid"]]
    bad = [s for s in sequences if not s["mermaid"]]
    assert len(good) == 1 and len(bad) == 1
    assert bad[0]["fallback_text"]


async def test_generate_sequences_empty_when_no_core_modules():
    tree = ProjectTree(
        project_id="p1",
        modules=[ModuleNode(key="shared:shared", name="shared", kind="shared", files=[])],
    )
    llm = FakeLLM()
    assert await generate_sequences(tree, GraphEdges(), llm) == ([], 0, 0)
    assert llm.seq_calls == []  # 无核心模块时不调 LLM
