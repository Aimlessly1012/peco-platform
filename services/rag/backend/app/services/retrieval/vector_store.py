"""向量检索层：LangChain Neo4jVector 三路（M15 D1/D2/D3）。

chunk / file / module 三条路各挂一个 Neo4jVector 实例，project 过滤与 citation
字段投影写在 `retrieval_query` 定制插槽里（D2：Cypher 不消失，宿主从手写函数
换成框架插槽）。

下面四条是实测踩出来的，改之前务必读完：

1. **k 要传 fetch_k，切片在客户端做。** 库生成的 Cypher 形如

       CALL db.index.vector.queryNodes($idx, $top_k * $ratio, $vec) YIELD node, score
       WITH node, score LIMIT $top_k     ← 截断在前
       <我们的 retrieval_query>           ← project 过滤在后

   LIMIT 排在过滤之前：多项目库上直接按 k 取会拿不满，甚至拿到 0 条。所以按
   k × FETCH_MULTIPLIER 取回再自己切 k，语义与 M2 手写版的「先过滤后 LIMIT」
   完全等价（test_langchain_retrieval.py 有逐条对照钉住）。
   顺带记一笔：改走库的 `filter=` 参数更糟——它会整个放弃向量索引，退化成
   `MATCH (node:Chunk) ... vector.similarity.cosine(...)` 全表暴力扫。

2. **metadata 里值为 null 的键会被库丢掉**（Document 构造时过滤 None）。所以
   Python 侧一律 `props.get(key, 默认值)`，默认值与 M2 手写版逐个对齐。

3. **text 为 null 会让整次检索抛 ValueError**（不是跳过那一条，是整次失败）。
   摘要可能为空的两路必须 coalesce 成空串。

4. **纯向量检索也被强制要求传 `query` kwarg**（库里只有 hybrid 用得上，属实现
   疏漏）。传原始问题文本即可。

Neo4jVector 内部是 neo4j **同步**驱动、无原生 async 实现，所以调用一律过
asyncio.to_thread；构造实例会 verify_connectivity，必须缓存复用。
"""
import asyncio
import logging
import threading

from app.core.config import settings
from app.services.retrieval.models import (
    RetrievedItem,
    chunk_item,
    file_item,
    module_item,
)

logger = logging.getLogger(__name__)

CHUNK_INDEX = "chunk_embedding"
FILE_INDEX = "file_summary_embedding"
MODULE_INDEX = "module_summary_embedding"

# over-fetch 倍数：与 M2 手写版的 fetch_k = k * 4 一致
FETCH_MULTIPLIER = 4

_FILTER = "WITH node, score WHERE node.project_id = $pid"

# 插槽里的 metadata 一律用 Neo4j 原始属性名，好让 models.py 的构造器同时服务
# 向量层与图扩展层（见 models 模块注释）。正文走 text，回来再拼回 props。
RETRIEVAL_QUERIES: dict[str, str] = {
    CHUNK_INDEX: f"""{_FILTER}
        RETURN coalesce(node.code, '') AS text, score AS score,
               {{name: node.name, file_path: node.file_path, symbol: node.symbol,
                 symbol_type: node.symbol_type, start_line: node.start_line,
                 end_line: node.end_line}} AS metadata""",
    FILE_INDEX: f"""{_FILTER}
        RETURN coalesce(node.summary, '') AS text, score AS score,
               {{name: node.name, path: node.path}} AS metadata""",
    MODULE_INDEX: f"""{_FILTER}
        RETURN coalesce(node.summary, '') AS text, score AS score,
               {{name: node.name, module_name: node.module_name}} AS metadata""",
}

# Document → props 时正文回填到哪个原始属性名上
_TEXT_PROPERTY = {CHUNK_INDEX: "code", FILE_INDEX: "summary", MODULE_INDEX: "summary"}
_ITEM_BUILDER = {CHUNK_INDEX: chunk_item, FILE_INDEX: file_item, MODULE_INDEX: module_item}

_embeddings = None
_stores: dict[str, object] = {}
_lock = threading.Lock()


def retrieval_embeddings():
    """检索侧的 Embeddings 组件（D3）。

    check_embedding_ctx_length=False 是必须的：默认开着时 LangChain 会用 tiktoken
    把长文本切块、分别嵌入再加权平均，出来的向量和索引侧 embedder 直接调 API 得到的
    不是一个东西——那等于悄悄换了向量空间。关掉之后两条路径发出的 HTTP 请求实测
    逐字节相同（URL/model/dimensions/encoding_format 全一致），同一服务端必然同向量。

    索引侧 embedder 的批量/退避/截断护栏原样保留，不合并实现（D3）。
    """
    global _embeddings
    if _embeddings is None:
        from langchain_openai import OpenAIEmbeddings

        _embeddings = OpenAIEmbeddings(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key or "unset",
            model=settings.embedding_model,
            dimensions=settings.embedding_dim,
            timeout=settings.embedding_timeout_seconds,
            check_embedding_ctx_length=False,
        )
    return _embeddings


async def embed_query(text: str) -> list[float]:
    """问题向量。截断口径与索引侧一致（同一模型的输入上限是同一个）。"""
    return await retrieval_embeddings().aembed_query(text[: settings.embedding_max_chars])


def get_store(index_name: str):
    """取（或惰性建）某条路的 Neo4jVector。

    embedding_dimension 必须显式传：不传的话库会拿 embed_query("foo") 去问模型要
    维度——每建一个实例多一次跨境嵌入调用，纯属白费。
    """
    store = _stores.get(index_name)
    if store is not None:
        return store
    with _lock:
        if index_name not in _stores:
            from langchain_neo4j import Neo4jVector

            _stores[index_name] = Neo4jVector.from_existing_index(
                embedding=retrieval_embeddings(),
                url=settings.neo4j_uri,
                username=settings.neo4j_user,
                password=settings.neo4j_password,
                index_name=index_name,
                embedding_dimension=settings.embedding_dim,
                retrieval_query=RETRIEVAL_QUERIES[index_name],
            )
            logger.info("Neo4jVector 已就绪：%s", index_name)
        return _stores[index_name]


def reset_stores() -> None:
    """丢弃缓存的实例与嵌入组件（测试、或配置热变更后用）。"""
    global _embeddings
    with _lock:
        for store in _stores.values():
            driver = getattr(store, "_driver", None)
            if driver is not None:
                driver.close()
        _stores.clear()
        _embeddings = None


def _to_item(index_name: str, doc, score: float) -> RetrievedItem:
    props = {**doc.metadata, _TEXT_PROPERTY[index_name]: doc.page_content}
    return _ITEM_BUILDER[index_name](props, score)


async def vector_route(
    index_name: str, vec: list[float], project_id: str, k: int, query: str = ""
) -> list[RetrievedItem]:
    """一条向量路的检索结果（已按分数降序，长度 ≤ k）。"""
    if k <= 0:
        return []
    store = get_store(index_name)
    hits = await asyncio.to_thread(
        store.similarity_search_with_score_by_vector,
        embedding=vec,
        k=k * FETCH_MULTIPLIER,   # 见模块注释第 1 条
        query=query,              # 见模块注释第 4 条
        params={"pid": str(project_id)},
    )
    return [_to_item(index_name, doc, score) for doc, score in hits[:k]]
