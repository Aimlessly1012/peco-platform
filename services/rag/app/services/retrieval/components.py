"""检索链的自持组件：RRF 融合与重排（M15 D1/D4）。

按**当代 1.x 风格**自持实现，不引 langchain-classic 的 EnsembleRetriever /
ContextualCompressionRetriever——官方已把那两个归为上一代，刚把编排换成
LangGraph 1.x 就往回引 legacy 组件说不过去（D1）。

RRF 的算法与 M7 之前的手写版逐行等价；rerank 的内核也一行没动（硅基流动
/v1/rerank 是 Cohere 风格、非 OpenAI 标准接口，没有官方 LangChain 集成，D4），
这里只是把它们包成与 LangGraph 节点签名对齐的组件形状。
"""
import logging

from app.core.config import settings
from app.services.retrieval import reranker
from app.services.retrieval.models import RetrievedItem

logger = logging.getLogger(__name__)

RRF_K = 60


class ReciprocalRankFuser:
    """多路检索结果的 RRF 融合。

    合并后 item.score 被改写为 RRF 分——前端引用排序跟着它走，别在别处再排一次。
    """

    def __init__(self, k: int = RRF_K) -> None:
        self.k = k

    def fuse(
        self, routes: list[list[RetrievedItem]], top_k: int
    ) -> list[RetrievedItem]:
        scores: dict[str, float] = {}
        items: dict[str, RetrievedItem] = {}
        for route in routes:
            for rank, item in enumerate(route):
                scores[item.node_id] = (
                    scores.get(item.node_id, 0.0) + 1.0 / (self.k + rank + 1)
                )
                if item.node_id not in items:
                    items[item.node_id] = item
        merged = sorted(items.values(), key=lambda i: scores[i.node_id], reverse=True)
        for item in merged:
            item.score = scores[item.node_id]
        return merged[:top_k]


class RerankCompressor:
    """候选池 → 精排 top_n（M7 D2）。

    任何失败（未开启/超时/坏响应）都保持入参顺序并截到 top_n——精排是锦上添花，
    绝不能因为它挂了就答不出问题。
    """

    def is_enabled(self) -> bool:
        return reranker.is_enabled()

    @staticmethod
    def document_text(item: RetrievedItem) -> str:
        """送去精排的文档文本：chunk 是代码、摘要节点是摘要（D2）。

        带上文件路径与符号名作头——纯代码片段常常看不出它属于什么业务，
        重排模型拿到定位信息判得更准。
        """
        head = item.file_path or item.symbol
        if item.symbol and item.symbol not in ("(file)", head):
            head = f"{head} :: {item.symbol}"
        body = item.content or ""
        return f"{head}\n{body}" if head else body

    async def compress(
        self, query: str, items: list[RetrievedItem], top_n: int
    ) -> list[RetrievedItem]:
        if not items:
            return items
        ranking = await reranker.rerank(
            query, [self.document_text(item) for item in items], top_n=top_n
        )
        if ranking is None:
            return items[:top_n]
        reordered: list[RetrievedItem] = []
        for index, score in ranking[:top_n]:
            item = items[index]
            item.score = score   # 分数改由重排模型给出，前端引用排序随之一致
            reordered.append(item)
        return reordered


rrf_fuser = ReciprocalRankFuser()
rerank_compressor = RerankCompressor()
