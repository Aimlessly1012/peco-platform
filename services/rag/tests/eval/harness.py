"""检索指标 harness（M17 3.3）。

直调 `search_layered`——不经 HTTP、不经 qa_graph、不经问答 LLM，测的就是检索本身。
指标：hit@k、recall@k、MRR，按 query 出明细、按 question_type 与总体出均值。

两种用法：
- 真实模型档（scripts/eval_retrieval.py）：算指标，看召回质量
- 离线确定性档（tests/test_retrieval_eval.py）：只取 node_id 序列做快照比对
  （fake 向量是 md5 词袋，没有语义能力，指标数值没有参考价值，只能证明管线没变）

配置指纹进报告头部：top_k 与 rerank 三项一变，指标就不可比，必须能一眼看出来。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings
from app.services.retrieval.service import search_layered

GOLDEN_PATH = Path(__file__).with_name("golden_set.json")
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

QUESTION_TYPES = ("local", "global", "impact")


@dataclass(frozen=True)
class GoldenQuery:
    id: str
    query: str
    question_type: str
    expect_files: tuple[str, ...] = ()
    expect_modules: tuple[str, ...] = ()
    expect_symbols: tuple[str, ...] = ()

    @property
    def expected_count(self) -> int:
        """期望命中的目标总数，recall 的分母。"""
        return len(self.expect_files) + len(self.expect_modules)


def load_golden(path: Path | None = None) -> list[GoldenQuery]:
    data = json.loads((path or GOLDEN_PATH).read_text(encoding="utf-8"))
    out = [
        GoldenQuery(
            id=q["id"],
            query=q["query"],
            question_type=q["question_type"],
            expect_files=tuple(q.get("expect_files", ())),
            expect_modules=tuple(q.get("expect_modules", ())),
            expect_symbols=tuple(q.get("expect_symbols", ())),
        )
        for q in data["queries"]
    ]
    bad = [q.id for q in out if q.question_type not in QUESTION_TYPES]
    if bad:
        raise ValueError(f"golden 集里有非法 question_type: {bad}")
    empty = [q.id for q in out if q.expected_count == 0]
    if empty:
        raise ValueError(f"golden 集里有没标期望命中的条目: {empty}")
    return out


def config_fingerprint() -> dict[str, Any]:
    """指标可比的前提。任何一项变化都会让跨次对比失去意义。"""
    return {
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_enabled": bool(getattr(settings, "rerank_enabled", False)),
        "rerank_model": getattr(settings, "rerank_model", "") or "",
        "rerank_candidate_multiplier": getattr(settings, "rerank_candidate_multiplier", 0),
        "embedding_model": getattr(settings, "embedding_model", "") or "",
        "embedding_dim": settings.embedding_dim,
    }


def fingerprint_line(fp: dict[str, Any] | None = None) -> str:
    fp = fp or config_fingerprint()
    return " ".join(f"{k}={v}" for k, v in sorted(fp.items()))


def _matches(item: Any, q: GoldenQuery) -> str | None:
    """结果项命中了哪个期望目标（返回目标标识），没命中返回 None。"""
    if item.kind == "module_summary":
        return f"module:{item.symbol}" if item.symbol in q.expect_modules else None
    return f"file:{item.file_path}" if item.file_path in q.expect_files else None


@dataclass
class QueryResult:
    query: GoldenQuery
    node_ids: list[str]
    hit: bool
    recall: float
    mrr: float
    first_hit_rank: int | None
    matched: list[str] = field(default_factory=list)


def score_one(q: GoldenQuery, items: Iterable[Any], k: int) -> QueryResult:
    top = list(items)[:k]
    matched: list[str] = []
    first_rank: int | None = None
    for rank, item in enumerate(top, start=1):
        target = _matches(item, q)
        if target is None or target in matched:
            continue
        matched.append(target)
        if first_rank is None:
            first_rank = rank
    return QueryResult(
        query=q,
        node_ids=[i.node_id for i in top],
        hit=bool(matched),
        recall=len(matched) / q.expected_count if q.expected_count else 0.0,
        mrr=(1.0 / first_rank) if first_rank else 0.0,
        first_hit_rank=first_rank,
        matched=matched,
    )


def stabilize(items: list[Any]) -> list[Any]:
    """并列分数下按 node_id 定序。

    RRF 会产出大量完全相同的融合分（三路各自 rank 组合出同值很常见），此时最终顺序
    取决于上游 Neo4j 向量查询在并列时的返回顺序——那个顺序本身不保证稳定，实测同一份
    数据在库里节点变多之后就会换位。钉这种顺序只会得到随机红灯，所以先按
    (分数降序, node_id 升序) 定序再记录。

    这不会掩盖真实漂移：分数变了顺序照样变。被消掉的只有「分数相同、上游顺序抖动」
    这一类假信号。
    """
    return sorted(items, key=lambda i: (-round(float(i.score), 6), i.node_id))


async def run_eval(
    project_id: str,
    queries: list[GoldenQuery] | None = None,
    top_k: int | None = None,
    strip_prefix: str | None = None,
) -> list[QueryResult]:
    """逐条跑检索并打分。

    strip_prefix 用于快照：node_id 前缀是随机 project_id，存进快照前替换成占位符。
    """
    queries = queries or load_golden()
    k = top_k or settings.retrieval_top_k
    results: list[QueryResult] = []
    for q in queries:
        items = stabilize(await search_layered(project_id, q.query, q.question_type, top_k=k))
        r = score_one(q, items, k)
        if strip_prefix:
            r.node_ids = [n.replace(strip_prefix, "{project}") for n in r.node_ids]
        results.append(r)
    return results


def summarize(results: list[QueryResult]) -> dict[str, dict[str, float]]:
    """按 question_type 与总体汇总均值。"""

    def agg(rs: list[QueryResult]) -> dict[str, float]:
        n = len(rs) or 1
        return {
            "queries": len(rs),
            "hit_rate": round(sum(r.hit for r in rs) / n, 4),
            "recall": round(sum(r.recall for r in rs) / n, 4),
            "mrr": round(sum(r.mrr for r in rs) / n, 4),
        }

    out = {"overall": agg(results)}
    for qt in QUESTION_TYPES:
        subset = [r for r in results if r.query.question_type == qt]
        if subset:
            out[qt] = agg(subset)
    return out


def format_report(results: list[QueryResult], top_k: int, title: str = "检索评测") -> str:
    """人读报告：头部配置指纹 + 按 query 明细 + 汇总。"""
    lines = [
        f"# {title}",
        "",
        f"config: {fingerprint_line()} eval_top_k={top_k}",
        f"queries: {len(results)}",
        "",
        "## 明细",
        "",
        f"| {'id':<10} | {'type':<7} | hit | recall | mrr  | 首个命中位次 | 命中目标 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.query.id:<10} | {r.query.question_type:<7} | "
            f"{'✓' if r.hit else '✗'} | {r.recall:.2f} | {r.mrr:.2f} | "
            f"{r.first_hit_rank or '-'} | {', '.join(r.matched) or '-'} |"
        )
    lines += ["", "## 汇总", ""]
    summary = summarize(results)
    lines.append("| 分组 | 条数 | hit@k | recall@k | MRR |")
    lines.append("|---|---|---|---|---|")
    for name, m in summary.items():
        lines.append(
            f"| {name} | {m['queries']} | {m['hit_rate']:.4f} | {m['recall']:.4f} | {m['mrr']:.4f} |"
        )
    return "\n".join(lines)


def snapshot_payload(results: list[QueryResult], top_k: int) -> dict[str, Any]:
    """离线快照内容：只有 node_id 序列，绝不含分数（D2：score 被覆写三次）。"""
    return {
        "config": config_fingerprint() | {"eval_top_k": top_k},
        "queries": {r.query.id: r.node_ids for r in results},
    }


def snapshot_path(question_type: str) -> Path:
    return SNAPSHOT_DIR / f"{question_type}.json"
