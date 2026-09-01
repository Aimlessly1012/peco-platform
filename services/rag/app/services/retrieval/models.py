"""检索结果的领域模型与构造器。

M15 把它从 service.py 拆出来：向量层（vector_store）与图扩展层（graph_expansion）
都要构造 RetrievedItem，放在 service.py 会成环。

构造器一律吃 Neo4j 的**原始属性名**（name/code/path/summary/...），这样向量层从
Document.metadata 还原和图扩展层从节点 props 直接读，走的是同一段映射代码——
「重构后引用字段不变」这条红线因此是结构保证，不靠两处各写一遍对齐。
"""
from dataclasses import dataclass


@dataclass
class RetrievedItem:
    kind: str            # chunk | file_summary | module_summary
    node_id: str
    file_path: str       # module_summary 时为空串
    symbol: str
    symbol_type: str
    start_line: int
    end_line: int
    content: str         # 代码或摘要文本
    score: float
    via_edge: str | None = None  # None=直接命中；defines_file/calls_api/imports=关联带出

    def citation(self) -> dict:
        """出处条目。顺序与提示词里的「资料 N」编号一一对应（N = 下标 + 1），
        答案中的 [n] 上标即按此定位，因此关联带出项也必须在列，不能过滤。"""
        return {
            "file_path": self.file_path or f"[模块] {self.symbol}",
            "start_line": self.start_line,
            "end_line": self.end_line,
            "node_id": self.node_id,
            "symbol": self.symbol,
            "kind": self.kind,          # chunk / file_summary / module_summary
            "via_edge": self.via_edge,  # None=直接命中；其余为关联带出的边类型
        }


def chunk_item(props: dict, score: float, via: str | None = None) -> RetrievedItem:
    return RetrievedItem(
        kind="chunk",
        node_id=props.get("name", ""),
        file_path=props.get("file_path", ""),
        symbol=props.get("symbol", ""),
        symbol_type=props.get("symbol_type", ""),
        start_line=props.get("start_line", 0),
        end_line=props.get("end_line", 0),
        content=props.get("code", ""),
        score=score,
        via_edge=via,
    )


def file_item(props: dict, score: float, via: str | None = None) -> RetrievedItem:
    return RetrievedItem(
        kind="file_summary",
        node_id=props.get("name", ""),
        file_path=props.get("path", ""),
        symbol="(file)",
        symbol_type="file",
        start_line=0,
        end_line=0,
        content=props.get("summary", ""),
        score=score,
        via_edge=via,
    )


def module_item(props: dict, score: float) -> RetrievedItem:
    return RetrievedItem(
        kind="module_summary",
        node_id=props.get("name", ""),
        file_path="",
        symbol=props.get("module_name") or props.get("name", "").split(":module:")[-1],
        symbol_type="module",
        start_line=0,
        end_line=0,
        content=props.get("summary", ""),
        score=score,
    )
