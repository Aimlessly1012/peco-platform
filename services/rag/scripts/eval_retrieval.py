#!/usr/bin/env python
"""真实模型检索评测（M17 3.5）——手动触发，会产生 API 费用。

用真 embedding（可选 rerank）在同一份 golden 集上跑 `search_layered`，产出 hit@k /
recall@k / MRR 报告。评测集与离线档同一份，所以两档的差距就是「fake 词袋 vs 真语义」
带来的召回差距。

用法（必须 cd backend，否则会加载错 .env）：

    cd backend
    uv run python scripts/eval_retrieval.py                    # 真 embedding，rerank 按 .env
    uv run python scripts/eval_retrieval.py --no-rerank        # 强制关掉 rerank
    uv run python scripts/eval_retrieval.py --top-k 8 --out ../docs/retrieval-baseline-run.md

前置：Neo4j 可达、.env 里 embedding 三件套配好。脚本自己建图、评完删图，不留残留。

⚠️ 花钱的地方：mini_repo 约 11 个文件，一次评测的 embedding 调用量很小（几十条文本 +
23 条 query），成本可忽略；开 rerank 会多 23 次 rerank 调用。真正贵的是 LLM 摘要——
默认用模板摘要（--real-summary 才走真 LLM），因为评测的是检索不是摘要质量。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.graph.client import (  # noqa: E402
    close_driver,
    delete_project_graph,
    ensure_vector_index,
)
from tests.eval.harness import (  # noqa: E402
    fingerprint_line,
    format_report,
    load_golden,
    run_eval,
    summarize,
)
from tests.helpers.fixture_graph import index_fixture_repo  # noqa: E402


class TemplateSummarizer:
    """模板摘要：评测检索质量时不必为摘要付 LLM 的钱。

    摘要文本仍会被真 embedding 向量化，所以 file/module 摘要层照样参与检索——
    只是摘要内容是结构化模板而非 LLM 生成。想评「LLM 摘要对召回的贡献」时加 --real-summary。
    """

    async def summarize_file(self, path, imports, chunks, content):
        symbols = ", ".join(c.symbol for c in chunks)
        return f"{path}：定义了 {symbols}；导入 {', '.join(sorted(imports)) or '无'}"

    async def summarize_module(self, name, kind, prefix, entries, extra):
        return f"模块 {name}（{kind}），路由前缀 {prefix or '无'}，入口文件 {', '.join(entries)}"

    async def summarize_project(self, readme, module_map, module_summaries):
        names = ", ".join(m.name for m in module_map.modules)
        return f"mini-shop 示例项目，包含模块：{names}"


async def main() -> int:
    parser = argparse.ArgumentParser(description="真实模型检索评测")
    parser.add_argument("--top-k", type=int, default=settings.retrieval_top_k)
    parser.add_argument(
        "--no-rerank", action="store_true", help="强制关闭 rerank（默认跟随 .env 配置）"
    )
    parser.add_argument(
        "--real-summary", action="store_true", help="用真 LLM 生成摘要（更贵，默认模板摘要）"
    )
    parser.add_argument("--out", type=Path, help="报告写入文件（默认只打印）")
    args = parser.parse_args()

    if args.no_rerank:
        settings.rerank_base_url = ""
        settings.rerank_api_key = ""
        settings.rerank_model = ""

    if not settings.embedding_api_key:
        print("缺少 embedding 配置（EMBEDDING_API_KEY），无法跑真实档", file=sys.stderr)
        return 1

    from app.services.ingest.embedder import embedder

    if args.real_summary:
        from app.services.ingest.summarizer import summarizer
    else:
        summarizer = TemplateSummarizer()

    queries = load_golden()
    pid = f"eval-real-{uuid.uuid4().hex[:8]}"
    print(f"[1/3] 建图（真 embedding{'，真 LLM 摘要' if args.real_summary else '，模板摘要'}）…", file=sys.stderr)

    await ensure_vector_index()
    try:
        await index_fixture_repo(pid, embedder, summarizer)
        print(f"[2/3] 跑 {len(queries)} 条 golden 查询…", file=sys.stderr)
        results = await run_eval(pid, queries, top_k=args.top_k)

        title = (
            f"真实模型检索评测 · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        report = format_report(results, args.top_k, title=title)
        report += (
            f"\n\n摘要来源: {'真实 LLM' if args.real_summary else '模板（未调用 LLM）'}\n"
            f"语料: services/rag/tests/fixtures/mini_repo\n"
        )

        print(f"[3/3] 完成\n", file=sys.stderr)
        print(report)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(report + "\n", encoding="utf-8")
            print(f"\n报告已写入 {args.out}", file=sys.stderr)

        overall = summarize(results)["overall"]
        print(
            f"\nhit@{args.top_k}={overall['hit_rate']:.4f} "
            f"recall@{args.top_k}={overall['recall']:.4f} "
            f"MRR={overall['mrr']:.4f}",
            file=sys.stderr,
        )
        print(f"config: {fingerprint_line()}", file=sys.stderr)
    finally:
        await delete_project_graph(pid)
        await close_driver()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
