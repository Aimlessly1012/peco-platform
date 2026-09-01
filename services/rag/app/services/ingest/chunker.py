"""tree-sitter AST 分块器。

切块规则（spec: AST 分块）：
- 顶层函数 / 类 / 导出声明各成一块；类超长时按方法二次切
- 模块级零散语句（import 等）合并为一个 module-level 块
- 超长块按字符数二次切分，共享符号元数据
- 单文件解析失败由调用方跳过（抛 ChunkError）
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from app.core.config import settings
from app.services.ingest.walker import LANGUAGE_BY_EXT

# 粗估 1 token ≈ 4 字符（代码）
MAX_CHARS = settings.chunk_max_tokens * 4

PY_DEF_TYPES = {"function_definition", "class_definition", "decorated_definition"}
JS_DEF_TYPES = {
    "function_declaration", "generator_function_declaration", "class_declaration",
    "abstract_class_declaration", "lexical_declaration", "variable_declaration",
    "interface_declaration", "type_alias_declaration", "enum_declaration",
}


class ChunkError(Exception):
    pass


@dataclass
class CodeChunk:
    file_path: str  # 仓库内相对路径
    language: str
    symbol: str
    symbol_type: str  # function | class | method | module
    start_line: int  # 1-based
    end_line: int
    code: str
    content_hash: str


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()[:16]


def _node_text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _name_of(source: bytes, node: Node) -> str | None:
    """尽力提取定义节点的符号名。"""
    if node.type == "decorated_definition":
        inner = node.child_by_field_name("definition")
        return _name_of(source, inner) if inner else None
    if node.type == "export_statement":
        inner = node.child_by_field_name("declaration")
        return _name_of(source, inner) if inner else None
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(source, name_node)
    # lexical_declaration / variable_declaration: 取第一个 declarator 的 name
    for child in node.named_children:
        if child.type == "variable_declarator":
            n = child.child_by_field_name("name")
            if n is not None:
                return _node_text(source, n)
    return None


def _symbol_type_of(node: Node) -> str:
    t = node.type
    if node.type == "decorated_definition":
        inner = node.child_by_field_name("definition")
        t = inner.type if inner else t
    if node.type == "export_statement":
        inner = node.child_by_field_name("declaration")
        t = inner.type if inner else t
    if "class" in t:
        return "class"
    return "function"


def _split_oversized(chunk: CodeChunk) -> list[CodeChunk]:
    """超长块按字符数硬切，共享符号元数据（spec: 超长二次切分）。"""
    if len(chunk.code) <= MAX_CHARS:
        return [chunk]
    parts: list[CodeChunk] = []
    lines = chunk.code.splitlines(keepends=True)
    buf: list[str] = []
    size = 0
    part_start = chunk.start_line
    line_no = chunk.start_line
    for line in lines:
        buf.append(line)
        size += len(line)
        line_no += 1
        if size >= MAX_CHARS:
            code = "".join(buf)
            parts.append(
                CodeChunk(
                    chunk.file_path, chunk.language,
                    f"{chunk.symbol}#part{len(parts) + 1}", chunk.symbol_type,
                    part_start, line_no - 1, code, _hash(code),
                )
            )
            buf, size, part_start = [], 0, line_no
    if buf:
        code = "".join(buf)
        parts.append(
            CodeChunk(
                chunk.file_path, chunk.language,
                f"{chunk.symbol}#part{len(parts) + 1}" if parts else chunk.symbol,
                chunk.symbol_type, part_start, chunk.end_line, code, _hash(code),
            )
        )
    return parts


def _class_methods(source: bytes, class_node: Node, class_name: str, rel_path: str, language: str) -> list[CodeChunk]:
    """超长类按方法二次切（spec: 类超长按方法切）。"""
    body = class_node.child_by_field_name("body")
    if body is None:
        return []
    chunks: list[CodeChunk] = []
    for child in body.named_children:
        target = child
        if child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            target = inner if inner else child
        if target.type in {"function_definition", "method_definition"}:
            name = _name_of(source, target) or "(anonymous)"
            code = _node_text(source, child)
            chunks.append(
                CodeChunk(
                    rel_path, language, f"{class_name}.{name}", "method",
                    child.start_point[0] + 1, child.end_point[0] + 1,
                    code, _hash(code),
                )
            )
    return chunks


def chunk_file(repo_dir: Path, rel_path: Path) -> list[CodeChunk]:
    language = LANGUAGE_BY_EXT[rel_path.suffix.lower()]
    try:
        source = (repo_dir / rel_path).read_bytes()
        parser = get_parser(language)
        tree = parser.parse(source)
    except Exception as e:
        raise ChunkError(f"解析失败: {e}") from e
    if tree.root_node.has_error and not tree.root_node.named_children:
        raise ChunkError("语法错误，无可用 AST")

    def_types = PY_DEF_TYPES if language == "python" else JS_DEF_TYPES
    rel_str = str(rel_path)
    chunks: list[CodeChunk] = []
    module_parts: list[Node] = []

    for node in tree.root_node.named_children:
        actual = node
        if node.type == "export_statement":
            inner = node.child_by_field_name("declaration")
            if inner is not None and inner.type in def_types:
                actual = inner
            else:
                module_parts.append(node)
                continue
        if actual.type not in def_types:
            module_parts.append(node)
            continue

        symbol = _name_of(source, node) or "(anonymous)"
        symbol_type = _symbol_type_of(actual)
        code = _node_text(source, node)
        chunk = CodeChunk(
            rel_str, language, symbol, symbol_type,
            node.start_point[0] + 1, node.end_point[0] + 1, code, _hash(code),
        )
        if symbol_type == "class" and len(code) > MAX_CHARS:
            # 类头（去掉方法体细节由头部块承担语义）+ 方法块
            class_target = actual
            if actual.type == "decorated_definition":
                inner = actual.child_by_field_name("definition")
                class_target = inner if inner else actual
            methods = _class_methods(source, class_target, symbol, rel_str, language)
            if methods:
                chunks.extend(methods)
                continue
        chunks.extend(_split_oversized(chunk))

    if module_parts:
        code = "\n".join(_node_text(source, n) for n in module_parts)
        if code.strip():
            chunk = CodeChunk(
                rel_str, language, "(module)", "module",
                module_parts[0].start_point[0] + 1,
                module_parts[-1].end_point[0] + 1, code, _hash(code),
            )
            chunks.extend(_split_oversized(chunk))

    return chunks
