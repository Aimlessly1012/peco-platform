"""规则分级摘要与 L2 输入分级单测（M5 B6/B7）。

判定必须保守：误判成本是"业务文件拿到糊摘要"，而漏判只是多花一次 LLM 调用。
每条规则都要有"正例命中 + 近似反例不命中"两侧断言。
"""
import pytest

from app.services.ingest.chunker import CodeChunk
from app.services.ingest.summarizer import (
    FAST_PREFIX,
    fast_summary,
    rule_summary,
    template_module_summary,
    template_project_summary,
)


def chunk(symbol: str, symbol_type: str = "function", *, start=1, end=10, code="") -> CodeChunk:
    return CodeChunk(
        file_path="x.ts", language="typescript", symbol=symbol,
        symbol_type=symbol_type, start_line=start, end_line=end,
        code=code or f"function {symbol}() {{}}", content_hash="h",
    )


def module_chunk(code: str) -> CodeChunk:
    return CodeChunk(
        file_path="x.ts", language="typescript", symbol="(module)",
        symbol_type="module", start_line=1, end_line=5, code=code, content_hash="h",
    )


def big(symbols: list[CodeChunk]) -> list[CodeChunk]:
    """把符号撑到 30 行以上，避免命中"小文件"规则干扰其他规则的断言。"""
    return symbols + [chunk("filler", start=40, end=90)]


# ---------------- 测试文件 ----------------


@pytest.mark.parametrize(
    "path",
    [
        "src/__tests__/order.ts",
        "tests/test_order.py",
        "backend/test_orders.py",
        "src/order.test.ts",
        "src/order.spec.tsx",
        "e2e/checkout.e2e.ts",
    ],
)
def test_rule_test_files(path):
    summary = rule_summary(path, big([chunk("shouldCreateOrder")]))
    assert summary is not None
    assert "测试用例" in summary
    assert "shouldCreateOrder" in summary


@pytest.mark.parametrize(
    "path", ["src/contest/latest.ts", "src/protest.py", "src/attestation.ts"]
)
def test_rule_test_files_no_false_positive(path):
    """近似词（contest/protest/attestation）不能被当成测试文件。"""
    assert rule_summary(path, big([chunk("handler")])) is None


# ---------------- 类型定义 ----------------


def test_rule_declaration_file():
    summary = rule_summary("src/types/api.d.ts", big([chunk("ApiResponse", "interface")]))
    assert summary.startswith("类型定义：")


def test_rule_all_type_symbols():
    symbols = big([
        chunk("Order", "interface"),
        chunk("OrderStatus", "enum"),
        chunk("OrderId", "type"),
    ])
    # filler 是 function → 不应命中；去掉 filler 后应命中
    assert rule_summary("src/model.ts", symbols) is None

    only_types = [chunk("Order", "interface", start=1, end=40),
                  chunk("OrderStatus", "enum", start=41, end=80)]
    summary = rule_summary("src/model.ts", only_types)
    assert summary.startswith("类型定义：")
    assert "Order" in summary and "OrderStatus" in summary


def test_rule_type_file_with_one_function_is_not_type_only():
    """保守判定：混了一个函数就不算类型定义文件。"""
    symbols = [chunk("Order", "interface", start=1, end=40), chunk("build", start=41, end=80)]
    assert rule_summary("src/model.ts", symbols) is None


# ---------------- barrel ----------------


def test_rule_barrel_file():
    chunks = [module_chunk(
        "export { Button } from './Button';\nexport * from './Card';\n" + "\n" * 40
    )]
    summary = rule_summary("src/components/index.ts", chunks)

    assert summary.startswith("聚合导出：")
    assert "./Button" in summary and "./Card" in summary


def test_rule_barrel_requires_no_definitions():
    """有任何真实定义就不是 barrel。"""
    chunks = [
        module_chunk("export * from './Card';" + "\n" * 40),
        chunk("helper", start=41, end=80),
    ]
    assert rule_summary("src/components/index.ts", chunks) is None


# ---------------- 常量配置 ----------------


def test_rule_config_by_filename():
    summary = rule_summary("src/config.ts", big([chunk("apiBaseUrl", "lexical_declaration")]))
    assert summary.startswith("配置常量：")


def test_rule_constants_by_all_upper_symbols():
    symbols = [
        chunk("MAX_RETRY", "lexical_declaration", start=1, end=40),
        chunk("API_TIMEOUT", "lexical_declaration", start=41, end=80),
    ]
    summary = rule_summary("src/limits.ts", symbols)
    assert summary.startswith("配置常量：")


def test_rule_constants_needs_all_upper():
    symbols = [
        chunk("MAX_RETRY", "lexical_declaration", start=1, end=40),
        chunk("createOrder", start=41, end=80),
    ]
    assert rule_summary("src/limits.ts", symbols) is None


def test_rule_single_constant_not_enough():
    """单个大写常量不足以判定（保守：至少 2 个）。"""
    assert rule_summary("src/x.ts", [chunk("MAX", "lexical_declaration", start=1, end=80)]) is None


# ---------------- 小文件 ----------------


def test_rule_small_file():
    summary = rule_summary("src/util.ts", [chunk("formatDate", start=1, end=12)])
    assert summary.startswith("小文件（12 行）")
    assert "function formatDate" in summary


def test_rule_large_file_falls_through_to_llm():
    assert rule_summary("src/service.ts", [chunk("createOrder", start=1, end=200)]) is None


def test_rule_empty_chunks_falls_through():
    assert rule_summary("src/empty.ts", []) is None


def test_rule_priority_test_before_small():
    """规则按序判定：测试文件即使很小也走测试模板。"""
    summary = rule_summary("src/a.test.ts", [chunk("it", start=1, end=5)])
    assert "测试用例" in summary


# ---------------- fast 模式模板 ----------------


def test_fast_summary_is_prefixed():
    """FAST_PREFIX 让这类摘要不进缓存，deep 补跑时才能被真正的 LLM 摘要替换。"""
    summary = fast_summary("src/service.ts", [chunk("createOrder"), chunk("cancelOrder")])
    assert summary.startswith(FAST_PREFIX)
    assert "createOrder" in summary and "cancelOrder" in summary


def test_template_module_summary_is_prefixed():
    summary = template_module_summary("orders", "api", "/api/orders", ["a.py", "b.py"])
    assert summary.startswith(FAST_PREFIX)
    assert "含 2 个文件" in summary
    assert "a.py" in summary


def test_template_module_summary_truncates_file_list():
    files = [f"src/f{i}.ts" for i in range(30)]
    summary = template_module_summary("big", "page", "", files)
    assert "等 30 个文件" in summary
    assert "src/f20.ts" not in summary


def test_template_project_summary_lists_modules():
    from app.services.ingest.router_parser import ModuleMap, RouteModule

    module_map = ModuleMap(
        modules=[
            RouteModule(name="orders", kind="api", route_prefix="/api/orders"),
            RouteModule(name="home", kind="page", route_prefix="/"),
        ]
    )
    summary = template_project_summary(module_map)

    assert "共 2 个功能模块" in summary
    assert "[api] orders（路由 /api/orders）" in summary


# ---------------- L2 输入分级（B7） ----------------


class RecordingLLM:
    def __init__(self):
        self.prompts: list[str] = []

    async def complete(self, prompt: str):
        self.prompts.append(prompt)
        return "摘要"


@pytest.mark.parametrize(
    "end_line,expect_head",
    [(50, False), (300, True), (900, True)],
)
async def test_l2_input_tiering(monkeypatch, end_line, expect_head):
    """<100 行不给头部（省 token），100 行以上给头部。"""
    from app.services.ingest import summarizer as sm

    recorder = RecordingLLM()
    monkeypatch.setattr(
        type(sm.summarizer), "_complete",
        lambda self, prompt: recorder.complete(prompt),
    )

    head_text = "IMPORT_HEADER_MARKER" + "x" * 900
    await sm.summarizer.summarize_file(
        "src/service.ts", set(), [chunk("createOrder", start=1, end=end_line)], head_text
    )

    prompt = recorder.prompts[0]
    assert ("IMPORT_HEADER_MARKER" in prompt) is expect_head
    if not expect_head:
        assert "小文件，见符号清单" in prompt


async def test_l2_large_file_gets_more_head_budget(monkeypatch):
    from app.services.ingest import summarizer as sm

    recorder = RecordingLLM()
    monkeypatch.setattr(
        type(sm.summarizer), "_complete",
        lambda self, prompt: recorder.complete(prompt),
    )
    head_text = "H" * 2000

    await sm.summarizer.summarize_file(
        "a.ts", set(), [chunk("f", start=1, end=300)], head_text
    )
    await sm.summarizer.summarize_file(
        "b.ts", set(), [chunk("f", start=1, end=900)], head_text
    )

    medium_head = recorder.prompts[0].count("H")
    large_head = recorder.prompts[1].count("H")
    assert medium_head == 300
    assert large_head == 600
