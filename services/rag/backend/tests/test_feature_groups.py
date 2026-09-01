"""功能域业务归组单测（M6 B6）：阈值、JSON 解析、防幻觉校验与降级。

校验器是这块的防线：LLM 编出清单外的功能域名、漏掉一半、只归一个组，
都必须被挡住并退回平铺——宁可平铺也不能给用户一棵错的树。
"""
import pytest

from app.services.report.features import (
    GROUP_THRESHOLD,
    OTHER_GROUP,
    build_grouped_feature_map,
    build_group_input,
    domain_titles,
    domains_signature,
    feature_domains,
    generate_feature_map,
    group_feature_domains,
    parse_groups,
    validate_groups,
)
from app.services.report.graph_reader import FileNode, ModuleNode, ProjectTree
from tests.helpers.report import FakeLLM


def big_tree(count: int = 12) -> ProjectTree:
    """超过归组阈值的项目：taskCenter* 一族 + facebookBonus* 一族 + 其他。"""
    names = [
        "taskCenter", "taskCenterDetail", "taskList",
        "facebookBonus", "facebookBonusRule",
        "settings", "login", "profile", "report", "billing", "help", "about",
    ][:count]
    return ProjectTree(
        project_id="p", name="activity", summary="项目定位：运营活动平台",
        modules=[
            ModuleNode(
                key=f"page:{n}", name=n, kind="page", route_prefix=f"/{n}",
                summary=f"业务目标：{n} 相关能力\n关键流程：略",
                files=[FileNode(path=f"src/pages/{n}/index.tsx")],
            )
            for n in names
        ],
    )


def titles_of(tree: ProjectTree) -> dict[str, str]:
    return domain_titles(feature_domains(tree))


# ---------------- 阈值 ----------------


async def test_no_grouping_at_or_below_threshold():
    """≤8 个功能域保持三层平铺——本来就看得过来，归组反而多一层。"""
    tree = big_tree(GROUP_THRESHOLD)
    domains = feature_domains(tree)
    llm = FakeLLM()

    groups, source = await group_feature_domains(domains, titles_of(tree), llm)

    assert groups == {}
    assert source == "none"
    assert llm.group_calls == []


async def test_grouping_kicks_in_above_threshold():
    tree = big_tree(12)
    llm = FakeLLM(group_returns='{"任务中心": ["taskCenter", "taskCenterDetail", "taskList"], '
                                '"Facebook 奖励": ["facebookBonus", "facebookBonusRule"], '
                                '"其他": ["settings", "login", "profile", "report", '
                                '"billing", "help", "about"]}')

    groups, source = await group_feature_domains(
        feature_domains(tree), titles_of(tree), llm
    )

    assert source == "llm"
    assert groups["任务中心"] == ["taskCenter", "taskCenterDetail", "taskList"]
    assert len(llm.group_calls) == 1


# ---------------- JSON 解析 ----------------


def test_parse_groups_plain_json():
    assert parse_groups('{"任务中心": ["a", "b"]}') == {"任务中心": ["a", "b"]}


def test_parse_groups_tolerates_fence_and_prose():
    raw = '好的，分组如下：\n```json\n{"任务中心": ["a"]}\n```'
    assert parse_groups(raw) == {"任务中心": ["a"]}


@pytest.mark.parametrize("raw", ["", "没有 JSON", "[1,2,3]", "{坏 JSON", "{}"])
def test_parse_groups_bad_input(raw):
    assert parse_groups(raw) == {}


def test_parse_groups_drops_non_list_values():
    assert parse_groups('{"a": ["x"], "b": "不是列表", "c": []}') == {"a": ["x"]}


# ---------------- 防幻觉校验 ----------------


VALID = ["taskCenter", "taskList", "settings", "login"]


def test_validate_accepts_complete_grouping():
    groups, reason = validate_groups(
        {"任务中心": ["taskCenter", "taskList"], "账号": ["settings", "login"]}, VALID
    )
    assert reason == ""
    assert groups == {"任务中心": ["taskCenter", "taskList"], "账号": ["settings", "login"]}


def test_validate_drops_hallucinated_members():
    """编出来的功能域名必须被丢掉，不能进树。"""
    groups, reason = validate_groups(
        {"任务中心": ["taskCenter", "根本不存在的功能"], "账号": ["settings", "login", "taskList"]},
        VALID,
    )
    assert reason == ""
    assert "根本不存在的功能" not in groups["任务中心"]


def test_validate_deduplicates_members():
    """同一功能域被分进两个组时只保留第一个。"""
    groups, _ = validate_groups(
        {"甲": ["taskCenter", "taskList"], "乙": ["taskCenter", "settings", "login"]}, VALID
    )
    assert groups["甲"].count("taskCenter") == 1
    assert "taskCenter" not in groups["乙"]


def test_validate_puts_missing_into_other():
    """spec: 遗漏项自动归「其他」组，不能凭空消失。"""
    groups, reason = validate_groups({"任务中心": ["taskCenter", "taskList"]}, VALID)

    assert reason == ""
    assert set(groups[OTHER_GROUP]) == {"settings", "login"}


def test_validate_rejects_single_group():
    """spec: 只有一个组 = 归组无意义，视为失败。"""
    _, reason = validate_groups({"全部": VALID}, VALID)
    assert "只归出一个组" in reason


def test_validate_rejects_tech_group_names():
    _, reason = validate_groups(
        {"用户模块": ["taskCenter"], "订单服务": ["taskList", "settings", "login"]}, VALID
    )
    assert "技术词" in reason


def test_validate_rejects_mostly_hallucinated():
    """过半成员不在清单内说明模型跑飞了，整体判失败而不是硬凑。"""
    _, reason = validate_groups(
        {"甲": ["假的一", "假的二", "假的三"], "乙": ["taskCenter"]}, VALID
    )
    assert "疑似幻觉" in reason


def test_validate_empty_input():
    _, reason = validate_groups({}, VALID)
    assert "未解析出分组" in reason


def test_validate_resolves_unique_path_suffix():
    """monorepo 域名是长路径时，LLM 常简写成尾段——唯一后缀要能映射回去。"""
    valid = ["infrastructure/src/pages/warehouse", "sites/report", "research/plans"]
    groups, reason = validate_groups(
        {"仓库站点": ["warehouse", "sites/report"], "研究管理": ["research/plans"]}, valid
    )
    assert reason == ""
    assert groups["仓库站点"] == ["infrastructure/src/pages/warehouse", "sites/report"]


def test_validate_drops_ambiguous_suffix():
    """两个域同尾段时简写有歧义，不赌——丢弃后进「其他」。"""
    valid = ["a/pages", "b/pages", "sites/report", "research/plans"]
    groups, _ = validate_groups(
        {"甲": ["pages", "sites/report"], "乙": ["research/plans"]}, valid
    )
    assert set(groups[OTHER_GROUP]) == {"a/pages", "b/pages"}


# ---------------- 降级与缓存 ----------------


@pytest.mark.parametrize(
    "returns",
    ["不是 JSON", None, '{"全部": ["taskCenter"]}', RuntimeError("超时")],
)
async def test_grouping_failure_falls_back_to_flat(returns):
    """spec: 归组失败保持平铺三层，不阻塞不报错（含一次重试）。"""
    tree = big_tree(12)
    llm = FakeLLM(group_returns=returns)

    groups, source = await group_feature_domains(
        feature_domains(tree), titles_of(tree), llm
    )

    assert groups == {}
    assert source == "none"
    assert len(llm.group_calls) == 2  # 失败重试一次后才放弃


async def test_grouping_retries_once_then_succeeds():
    """推理型模型偶发空输出/归类过粗——第二次成功就不降级。"""
    tree = big_tree(12)
    good = ('{"任务中心": ["taskCenter", "taskCenterDetail", "taskList"], '
            '"Facebook 奖励": ["facebookBonus", "facebookBonusRule"], '
            '"账号与权限": ["settings", "login", "profile"], '
            '"其他": ["report", "billing", "help", "about"]}')
    llm = FakeLLM(group_returns=[None, good])

    groups, source = await group_feature_domains(
        feature_domains(tree), titles_of(tree), llm
    )

    assert source == "llm"
    assert groups["任务中心"] == ["taskCenter", "taskCenterDetail", "taskList"]
    assert len(llm.group_calls) == 2


async def test_grouping_uses_cache():
    tree = big_tree(12)
    domains = feature_domains(tree)
    signature = domains_signature(domains)
    llm = FakeLLM()

    groups, source = await group_feature_domains(
        domains, titles_of(tree), llm, cache={signature: {"任务中心": ["taskCenter"]}}
    )

    assert source == "cache"
    assert groups == {"任务中心": ["taskCenter"]}
    assert llm.group_calls == []


def test_signature_changes_with_domain_set():
    assert domains_signature(feature_domains(big_tree(12))) != domains_signature(
        feature_domains(big_tree(11))
    )


def test_signature_stable_under_reordering():
    tree = big_tree(12)
    domains = feature_domains(tree)
    assert domains_signature(domains) == domains_signature(list(reversed(domains)))


def test_group_input_carries_business_goal():
    tree = big_tree(12)
    text = build_group_input(feature_domains(tree), titles_of(tree))
    assert "taskCenter" in text
    assert "相关能力" in text          # L3 业务目标首句
    assert "关键流程" not in text      # 只取业务目标那一节


# ---------------- 四层拼装 ----------------


def test_build_grouped_feature_map_is_four_levels():
    tree = big_tree(12)
    points = {m.key: [f"{m.name} 功能"] for m in tree.modules}
    groups = {
        "任务中心": ["taskCenter", "taskCenterDetail", "taskList"],
        "Facebook 奖励": ["facebookBonus", "facebookBonusRule"],
    }

    markdown = build_grouped_feature_map(tree, points, groups)
    lines = markdown.splitlines()

    assert lines[0].startswith("# activity：")
    assert "## 任务中心" in markdown
    assert "### taskCenter" in markdown
    assert "- taskCenter 功能" in markdown
    # 层级顺序：业务组 → 功能域 → 功能点
    group_at = lines.index("## 任务中心")
    assert lines[group_at + 1] == "### taskCenter"
    assert lines[group_at + 2] == "- taskCenter 功能"


def test_grouped_map_marks_domain_without_points():
    tree = big_tree(12)
    markdown = build_grouped_feature_map(tree, {}, {"任务中心": ["taskCenter"]})
    assert "（暂未提取到功能点）" in markdown


def test_grouped_map_ignores_unknown_titles():
    tree = big_tree(12)
    markdown = build_grouped_feature_map(tree, {}, {"任务中心": ["taskCenter", "不存在"]})
    assert "### 不存在" not in markdown


# ---------------- 端到端 ----------------


async def test_generate_feature_map_produces_four_levels():
    tree = big_tree(12)
    llm = FakeLLM(
        feature_returns="- 查看任务列表\n- 领取任务奖励",
        group_returns='{"任务中心": ["taskCenter", "taskCenterDetail", "taskList"], '
                      '"Facebook 奖励": ["facebookBonus", "facebookBonusRule"]}',
    )
    anchors = {m.key: [f"src/pages/{m.name}/index.tsx（Page）"] for m in tree.modules}

    markdown, _, stats = await generate_feature_map(tree, anchors, llm)

    assert stats["feature_groups"] == 3          # 两组 + 自动补的「其他」
    assert stats["feature_groups_source"] == "llm"
    assert "## 任务中心" in markdown
    assert "### taskCenter" in markdown
    assert f"## {OTHER_GROUP}" in markdown       # 遗漏项没丢


async def test_generate_feature_map_flat_when_grouping_fails():
    tree = big_tree(12)
    llm = FakeLLM(feature_returns="- 查看任务列表", group_returns="不是 JSON")

    markdown, _, stats = await generate_feature_map(tree, anchors_by_key := {}, llm)

    assert stats["feature_groups"] == 0
    assert stats["feature_groups_source"] == "none"
    assert "## taskCenter" in markdown           # 退回三层平铺
    assert "### taskCenter" not in markdown


async def test_fast_mode_never_groups():
    """fast 是零 LLM 档，归组也不能调。"""
    tree = big_tree(12)
    llm = FakeLLM()
    anchors = {m.key: [f"src/pages/{m.name}/index.tsx"] for m in tree.modules}

    markdown, _, stats = await generate_feature_map(tree, anchors, llm, fast=True)

    assert llm.group_calls == []
    assert stats["feature_groups"] == 0
    assert "## taskCenter" in markdown
