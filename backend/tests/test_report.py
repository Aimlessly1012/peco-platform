"""M3 报告生成单测（B2/B3）：思维导图程序化生成、mermaid 启发式校验、降级路径。

LLM 全部用 mock（FakeLLM），不触网；图数据用手写 dataclass，不依赖 Neo4j。
"""
import pytest

from app.services.report.builder import (
    MAX_EDGE_LINES,
    MAX_ENTRY_FILES,
    build_batch_input,
    build_fallback_text,
    build_module_context,
    build_module_lines,
    fallback_doc,
    generate_doc,
    generate_one_sequence,
    generate_sequences,
    select_core_modules,
    split_module_batches,
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
    """可编程假 LLM。

    chapter_returns 按批次依次取值（支持值、None、异常实例）；给单个值时所有批次复用它。
    """

    def __init__(
        self, chapter_returns=None, overview_returns="## 一、系统概述\n\n概述正文",
        seq_returns=None,
    ):
        self.chapter_returns = chapter_returns
        self.overview_returns = overview_returns
        self.seq_returns = list(seq_returns or [])
        self.chapter_calls: list[dict] = []
        self.overview_calls: list[tuple] = []
        self.seq_calls: list[dict] = []

    async def generate_chapters(self, module_blocks, count):
        self.chapter_calls.append({"blocks": module_blocks, "count": count})
        value = self.chapter_returns
        if isinstance(value, list):
            index = len(self.chapter_calls) - 1
            value = value[index] if index < len(value) else None
        if isinstance(value, Exception):
            raise value
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)

    async def generate_overview(self, overview, module_lines, chapter_titles):
        self.overview_calls.append((overview, module_lines, chapter_titles))
        if isinstance(self.overview_returns, Exception):
            raise self.overview_returns
        return self.overview_returns

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


def test_mindmap_is_two_level_only():
    """M5 spec 场景: 顶层导图节点数 ≤ 模块数 + 1（不含文件层）。"""
    tree = make_tree()
    out = build_mindmap(tree)
    lines = out.splitlines()

    assert lines[0] == "mindmap"
    assert lines[1] == '  root(("mini-shop"))'

    module_lines = [ln for ln in lines if ln.startswith("    ")]
    assert len(module_lines) == len(tree.modules)
    assert len(lines) == len(tree.modules) + 2  # mindmap 行 + root 行 + 模块行
    # 文件层已移除（改由前端按需拼装）
    assert "backend/routers/orders.py" not in out
    for m in tree.modules:
        assert m.name in out


def test_mindmap_scales_to_large_project():
    """49 模块 1160 文件的真实场景：节点数只跟模块数走。"""
    tree = ProjectTree(
        project_id="p1", name="big-app",
        modules=[
            ModuleNode(
                key=f"page:m{i}", name=f"m{i}", kind="page",
                files=[FileNode(path=f"src/pages/m{i}/f{j}.tsx") for j in range(24)],
            )
            for i in range(49)
        ],
    )
    out = build_mindmap(tree)

    assert len(out.splitlines()) == 49 + 2
    assert validate_mindmap(out) == (True, "")


def test_mindmap_module_label_carries_kind_prefix_and_count():
    out = build_mindmap(make_tree())
    assert "[接口] orders /api/orders · 2 文件" in out
    assert "[页面] orders /orders · 3 文件" in out
    assert "[共享] shared · 1 文件" in out


def test_mindmap_is_valid_by_self_check():
    assert validate_mindmap(build_mindmap(make_tree())) == (True, "")


def test_mindmap_empty_modules():
    tree = ProjectTree(project_id="p1", name="空项目")
    out = build_mindmap(tree)
    assert out.startswith("mindmap")
    assert "暂无模块数据" in out
    assert validate_mindmap(out)[0] is True


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


def test_module_context_truncates_to_main_path():
    """M5 D4: 入口 ≤5、每类边 ≤15，截断时 prompt 里注明只给主链路。"""
    files = [FileNode(path=f"src/f{i}.ts", summary=f"文件 {i}") for i in range(12)]
    mod = ModuleNode(key="page:big", name="big", kind="page", files=files)
    # 12 个文件、每个文件两条边 → 24 条，超过 15 的上限
    edges = GraphEdges(
        api_edges=[
            ApiEdgeInfo(
                src_file=f"src/f{i % 12}.ts", src_symbol=f"call{i}", src_start=i,
                dst_file="backend/api.py", dst_symbol=f"handler{i}", dst_start=i,
            )
            for i in range(24)
        ],
        import_edges=[
            ImportEdgeInfo(src=f"src/f{i % 12}.ts", dst=f"vendor/lib{i}.ts")
            for i in range(24)
        ],
    )

    ctx = build_module_context(mod, edges)

    assert len(ctx.entry_files) == MAX_ENTRY_FILES
    assert len([ln for ln in ctx.api_lines if "仅列出主链路" not in ln]) == MAX_EDGE_LINES
    assert len([ln for ln in ctx.import_lines if "仅列出主链路" not in ln]) == MAX_EDGE_LINES
    assert any("仅列出主链路" in line for line in ctx.api_lines)
    assert any("仅列出主链路" in line for line in ctx.import_lines)


def test_module_context_no_truncation_note_when_within_limits():
    tree = make_tree()
    mod = next(m for m in tree.modules if m.key == "api:orders")
    ctx = build_module_context(mod, make_edges())
    assert not any("仅列出主链路" in line for line in ctx.api_lines)


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


def big_tree(module_count: int = 49) -> ProjectTree:
    """49 模块的真实规模——把整篇塞一个 prompt 正是现在塌方的原因。"""
    kinds = ["api", "page", "dir"]
    return ProjectTree(
        project_id="p1", name="big-app", summary="大型全栈项目",
        modules=[
            ModuleNode(
                key=f"{kinds[i % 3]}:m{i}", name=f"m{i}", kind=kinds[i % 3],
                summary=f"m{i} 模块职责",
                files=[FileNode(path=f"src/m{i}/f{j}.ts") for j in range(3)],
            )
            for i in range(module_count)
        ],
    )


def test_split_module_batches_size_and_grouping():
    """M5 D3: 按 kind 分组、每批 ≤10 个模块。"""
    batches = split_module_batches(big_tree(49))

    assert all(len(b) <= 10 for b in batches)
    assert sum(len(b) for b in batches) == 49
    # 同一批内 kind 一致（分组切批的目的：章节风格稳定）
    assert all(len({m.kind for m in batch}) == 1 for batch in batches)


def test_split_module_batches_small_project():
    batches = split_module_batches(make_tree())
    assert sum(len(b) for b in batches) == 4
    assert all(len(b) <= 10 for b in batches)


async def test_generate_doc_map_reduce():
    llm = FakeLLM(chapter_returns="### 某模块（接口）\n**业务目标**：略")
    doc, fallback = await generate_doc(big_tree(49), llm)

    assert fallback is False
    assert len(llm.chapter_calls) == len(split_module_batches(big_tree(49)))
    assert len(llm.overview_calls) == 1          # reduce 只调一次
    assert doc.startswith("# big-app 需求逻辑文档")
    assert "## 一、系统概述" in doc
    assert "## 二、功能模块需求" in doc
    # 每批输入都远小于单 prompt 全量（现失败根因）
    assert all(call["count"] <= 10 for call in llm.chapter_calls)


async def test_generate_doc_single_batch_failure_does_not_collapse_document():
    """M5 spec 场景: 5 批中 1 批失败，其余章节与概述正常，仅该批降级标注。"""
    tree = big_tree(49)
    batches = split_module_batches(tree)
    returns = ["### 正常章节\n内容"] * len(batches)
    returns[1] = RuntimeError("上游 500")

    doc, fallback = await generate_doc(tree, FakeLLM(chapter_returns=returns))

    assert fallback is False                      # 整篇没塌
    assert "## 一、系统概述" in doc
    assert doc.count("### 正常章节") == len(batches) - 1
    assert f"有 1/{len(batches)} 批模块章节" in doc  # 降级被明确标注
    # 失败批的模块仍以原始摘要出现，不是整段消失
    failed_module = batches[1][0]
    assert failed_module.name in doc
    assert failed_module.summary in doc


@pytest.mark.parametrize("bad", [None, "", "   ", RuntimeError("上游 500")])
async def test_generate_doc_all_batches_fail_falls_back(bad):
    """全部批失败才算整篇降级（仍产出可读文档）。"""
    doc, fallback = await generate_doc(make_tree(), FakeLLM(chapter_returns=bad))

    assert fallback is True
    assert doc.startswith("# mini-shop 需求逻辑文档")
    assert "全栈演示项目：订单与用户" in doc      # L4
    assert "订单接口模块：创建与查询订单" in doc  # L3
    assert "backend/routers/orders.py" in doc     # 关键文件


async def test_generate_doc_overview_failure_uses_project_summary():
    """概述失败不影响已生成的章节。"""
    llm = FakeLLM(
        chapter_returns="### 某模块（接口）\n内容",
        overview_returns=RuntimeError("超时"),
    )
    doc, fallback = await generate_doc(make_tree(), llm)

    assert fallback is False
    assert "## 一、系统概述" in doc
    assert "全栈演示项目：订单与用户" in doc  # 回退用 L4 原文
    assert "### 某模块（接口）" in doc


async def test_generate_doc_strips_wrapping_fence():
    llm = FakeLLM(chapter_returns="```markdown\n### 模块\n正文\n```")
    doc, _ = await generate_doc(make_tree(), llm)
    assert "```markdown" not in doc
    assert "### 模块" in doc


def test_build_batch_input_contains_summary_and_files():
    tree = make_tree()
    text = build_batch_input([tree.modules[0]])

    assert "模块名：orders" in text
    assert "订单接口模块：创建与查询订单" in text
    assert "backend/routers/orders.py" in text


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
