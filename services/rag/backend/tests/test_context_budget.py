"""上下文预算裁剪与模型分工（M10 首答提速）。

背景：服务器实测首 token 61.9s，其中生成环节吃 10K 字符上下文喂推理型模型。
两个动作——裁上下文、生成换非推理模型——把首答压到 6s。

核心不变量：**裁的是 items 列表本身**。答案里的 [n] 上标按 items 下标定位，
citations 也来自同一个列表，只裁拼好的文本会让编号与右栏引用错位。
"""
import pytest

from app.core.config import settings
from app.services.qa.workflow import build_llm, fit_context_budget
from app.services.retrieval.service import RetrievedItem


def item(size: int, name: str = "fn") -> RetrievedItem:
    return RetrievedItem(
        kind="chunk", node_id=f"n:{name}", file_path=f"src/{name}.py", symbol=name,
        symbol_type="function", start_line=1, end_line=9, content="x" * size, score=0.9,
    )


@pytest.fixture
def budget(monkeypatch):
    """收窄预算便于构造边界，min_items 保持默认语义。"""
    def apply(char_budget: int, min_items: int = 4):
        monkeypatch.setattr(settings, "context_char_budget", char_budget)
        monkeypatch.setattr(settings, "context_min_items", min_items)
    return apply


# ---------------- 预算裁剪 ----------------


def test_keeps_all_when_under_budget(budget):
    budget(1000)
    items = [item(100) for _ in range(5)]
    assert fit_context_budget(items) == items


def test_trims_tail_when_over_budget(budget):
    """超预算时从尾部砍——items 已按相关性降序，尾部最不相关。"""
    budget(500, min_items=1)
    items = [item(200, f"f{i}") for i in range(5)]   # 累计 200/400/600...

    kept = fit_context_budget(items)

    assert len(kept) == 2                      # 第 3 条会到 600 > 500
    assert kept == items[:2]                   # 保留的是前缀，不是任意子集


def test_min_items_wins_over_budget(budget):
    """预算再紧也要给够条数，否则资料不足答不出来。"""
    budget(10, min_items=3)
    items = [item(500, f"f{i}") for i in range(5)]

    kept = fit_context_budget(items)

    assert len(kept) == 3


def test_zero_budget_disables_trimming(budget):
    """预算 0 = 关闭裁剪（留给不在乎延迟、要最大召回的场景）。"""
    budget(0)
    items = [item(9999, f"f{i}") for i in range(6)]
    assert fit_context_budget(items) == items


def test_kept_is_prefix_so_citation_numbering_holds(budget):
    """裁剪后 [n] 编号仍然指向同一条资料——这是不能破的不变量。"""
    budget(300, min_items=1)
    items = [item(100, f"f{i}") for i in range(6)]

    kept = fit_context_budget(items)

    # 保留项在原列表中的下标必须是 0..n-1 连续前缀，编号才不会错位
    assert [items.index(k) for k in kept] == list(range(len(kept)))


def test_empty_items(budget):
    budget(1000)
    assert fit_context_budget([]) == []


# ---------------- 模型分工 ----------------


@pytest.fixture(autouse=True)
def _llm_credentials(monkeypatch):
    """ChatOpenAI 构造期就校验 api_key，测试环境默认为空会直接抛。"""
    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(settings, "chat_base_url", "https://example.test/v1")


def test_generate_uses_generate_model(monkeypatch):
    monkeypatch.setattr(settings, "chat_model", "slow-reasoning-model")
    monkeypatch.setattr(settings, "generate_model", "fast-coder-model")

    assert build_llm(for_generate=True).model_name == "fast-coder-model"


def test_generate_falls_back_to_chat_model(monkeypatch):
    """没配 GENERATE_MODEL 时行为与 M10 之前完全一致。"""
    monkeypatch.setattr(settings, "chat_model", "slow-reasoning-model")
    monkeypatch.setattr(settings, "generate_model", "")

    assert build_llm(for_generate=True).model_name == "slow-reasoning-model"


def test_understand_never_uses_generate_model(monkeypatch):
    """理解/分类不受生成侧选型影响——它们各自的取舍不同。"""
    monkeypatch.setattr(settings, "chat_model", "slow-reasoning-model")
    monkeypatch.setattr(settings, "generate_model", "fast-coder-model")

    assert build_llm(streaming=False).model_name == "slow-reasoning-model"


def test_report_llm_prefers_summary_model(monkeypatch):
    """报告件与摘要同属离线产出，不能被在线问答的提速选型带走。"""
    from app.services.report.llm import ReportLLM

    monkeypatch.setattr(settings, "chat_model", "fast-coder-model")
    monkeypatch.setattr(settings, "summary_model", "quality-reasoning-model")
    assert ReportLLM().model == "quality-reasoning-model"

    monkeypatch.setattr(settings, "summary_model", "")
    assert ReportLLM().model == "fast-coder-model"
