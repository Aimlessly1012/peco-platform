"""重排（rerank）客户端（M7 D2）：硅基流动 /v1/rerank，Cohere 风格接口。

不是 OpenAI 标准接口，所以不走 openai SDK，httpx 直调：
    POST {base}/rerank  {"model", "query", "documents": [...], "top_n"}
    → {"id", "results": [{"index", "document": null, "relevance_score"}, ...], "meta"}

实测（硅基流动 Qwen3-Reranker-8B）：results 已按分数降序、document 回显 null
（不请求 return_documents，省流量）；错误响应形如 {"code", "data", "message"}，
非 2xx 或缺 results 字段都走降级。

错误哲学：任何异常/超时/坏响应都返回 None，由调用方保持原顺序——
精排是锦上添花，绝不能因为它挂了就答不出问题。
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    """三项配置齐全才算开启（任一为空 = 关闭，行为回到 M6）。"""
    return settings.rerank_enabled


def _prepare(documents: list[str]) -> list[str]:
    """截断 + 空文档占位：空字符串会被部分服务端判为非法请求。"""
    limit = settings.rerank_max_chars
    return [(doc or " ")[:limit] for doc in documents]


def parse_ranking(payload: dict, doc_count: int) -> list[tuple[int, float]] | None:
    """解析响应为 [(原下标, 分数)]（已按分数降序）。结构不符返回 None。"""
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    ranking: list[tuple[int, float]] = []
    for item in results:
        if not isinstance(item, dict):
            return None
        index = item.get("index")
        score = item.get("relevance_score", item.get("score"))
        if not isinstance(index, int) or index < 0 or index >= doc_count:
            return None
        if not isinstance(score, (int, float)):
            return None
        ranking.append((index, float(score)))
    if not ranking:
        return None
    ranking.sort(key=lambda pair: pair[1], reverse=True)
    return ranking


async def rerank(
    query: str, documents: list[str], top_n: int | None = None
) -> list[tuple[int, float]] | None:
    """精排。返回 [(原下标, 分数)] 降序；未开启或任何失败返回 None。"""
    if not is_enabled() or not query or not documents:
        return None

    payload = {
        "model": settings.rerank_model,
        "query": query,
        "documents": _prepare(documents),
        "top_n": min(top_n or len(documents), len(documents)),
    }
    url = settings.rerank_base_url.rstrip("/") + "/rerank"
    try:
        async with httpx.AsyncClient(timeout=settings.rerank_timeout_seconds) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {settings.rerank_api_key}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning("rerank 超时（%.1fs），保持原有排序", settings.rerank_timeout_seconds)
        return None
    except Exception as e:  # noqa: BLE001 — 精排失败绝不能阻塞问答
        logger.warning("rerank 调用失败（%s: %s），保持原有排序", type(e).__name__, e)
        return None

    ranking = parse_ranking(data, len(documents))
    if ranking is None:
        logger.warning("rerank 响应无法解析，保持原有排序")
    return ranking
