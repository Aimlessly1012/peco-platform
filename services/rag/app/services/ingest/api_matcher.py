"""CALLS_API 匹配：前端块 URL 字面量 ↔ 后端路由表，路径参数模式匹配（设计 D3）。"""
import re
from dataclasses import dataclass

from app.services.ingest.chunker import CodeChunk
from app.services.ingest.router_parser import BackendRoute

# 认封装函数：fetch / axios.get / apiGet / request / http.post 等，第一参为 '/...' 字符串
CALL_RE = re.compile(
    r"\b(?P<fn>fetch|axios(?:\.\w+)?|api\w*|request\w*|http\w*(?:\.\w+)?)\s*"
    r"(?:<[^>()]*>)?\s*\(\s*[`\"'](?P<url>/[^`\"']*)[`\"']",
    re.IGNORECASE,
)
METHOD_HINT_RE = re.compile(r"method\s*:\s*[\"'](\w+)[\"']", re.IGNORECASE)
TEMPLATE_SEG_RE = re.compile(r"\$\{[^}]*\}")


@dataclass
class ApiEdge:
    source_file: str
    source_symbol: str
    source_start_line: int
    target_file: str
    target_symbol: str


def _normalize(path: str) -> list[str]:
    path = path.split("?")[0].split("#")[0]
    path = TEMPLATE_SEG_RE.sub("{*}", path)
    return [
        "{*}" if (seg.startswith("{") or seg.startswith(":") or seg.startswith("[")) else seg
        for seg in path.split("/")
        if seg
    ]


def _infer_method(fn_name: str, code_after: str) -> str | None:
    lowered = fn_name.lower()
    for m in ("get", "post", "put", "delete", "patch"):
        if lowered.endswith(m):
            return m.upper()
    hint = METHOD_HINT_RE.search(code_after[:200])
    if hint:
        return hint.group(1).upper()
    return None


def _match(segs: list[str], method: str | None, route: BackendRoute) -> bool:
    route_segs = _normalize(route.path)
    if len(segs) != len(route_segs):
        return False
    for a, b in zip(segs, route_segs):
        if a != b and a != "{*}" and b != "{*}":
            return False
    return method is None or method == route.method


def extract_api_edges(
    frontend_chunks: list[CodeChunk],
    backend_routes: list[BackendRoute],
    chunks_by_file_symbol: dict[tuple[str, str], CodeChunk],
) -> tuple[list[ApiEdge], int]:
    """返回 (edges, warning_count)。warning = URL 提取到但没匹配上任何后端路由。"""
    edges: list[ApiEdge] = []
    warnings = 0
    seen: set[tuple] = set()

    for chunk in frontend_chunks:
        if chunk.language == "python":
            continue
        for m in CALL_RE.finditer(chunk.code):
            url = m.group("url")
            segs = _normalize(url)
            if not segs:
                continue
            method = _infer_method(m.group("fn"), chunk.code[m.end():])
            matched = [r for r in backend_routes if _match(segs, method, r)]
            if not matched:
                # 放宽 method 再试（apiGet 命名可能与后端 method 不严格一致）
                matched = [r for r in backend_routes if _match(segs, None, r)]
            if not matched:
                warnings += 1
                continue
            for route in matched:
                target = chunks_by_file_symbol.get((route.file, route.handler_symbol))
                if target is None:
                    continue
                key = (chunk.file_path, chunk.symbol, chunk.start_line, route.file, route.handler_symbol)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    ApiEdge(
                        source_file=chunk.file_path,
                        source_symbol=chunk.symbol,
                        source_start_line=chunk.start_line,
                        target_file=route.file,
                        target_symbol=target.symbol,
                    )
                )
    return edges, warnings
