"""IMPORTS 依赖边提取：仓库内相对/绝对导入 → File→File 边；三方包忽略。

Python: import a.b.c / from a.b import x / 相对导入
JS/TS:  import ... from './x' / require('./x')，'@/' 别名尝试常见根
"""
from pathlib import Path, PurePosixPath

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from app.services.ingest.walker import LANGUAGE_BY_EXT

JS_INDEX_CANDIDATES = [
    ".ts", ".tsx", ".js", ".jsx", ".mjs",
    "/index.ts", "/index.tsx", "/index.js", "/index.jsx",
]


def _node_text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


# ---------- Python ----------

def _py_module_candidates(dotted: str) -> list[str]:
    base = dotted.replace(".", "/")
    return [f"{base}.py", f"{base}/__init__.py"]


def _resolve_py_dotted(
    dotted: str, importer_dir: PurePosixPath, all_files: set[str]
) -> str | None:
    """绝对 dotted path：从 importer 所在目录逐级向上作为根尝试，最后全局后缀匹配。"""
    for cand in _py_module_candidates(dotted):
        search_dir = importer_dir
        while True:
            path = str(search_dir / cand) if str(search_dir) != "." else cand
            if path in all_files:
                return path
            if str(search_dir) in (".", ""):
                break
            search_dir = search_dir.parent
    # 全局后缀匹配（唯一时才采信）
    for cand in _py_module_candidates(dotted):
        matches = [f for f in all_files if f == cand or f.endswith("/" + cand)]
        if len(matches) == 1:
            return matches[0]
    return None


def _resolve_py_relative(
    level: int, dotted: str, importer_dir: PurePosixPath, all_files: set[str]
) -> str | None:
    base = importer_dir
    for _ in range(level - 1):
        base = base.parent
    prefix = "" if str(base) == "." else str(base) + "/"
    names = dotted.replace(".", "/") if dotted else ""
    candidates = (
        [f"{prefix}{names}.py", f"{prefix}{names}/__init__.py"]
        if names
        else [f"{prefix}__init__.py"]
    )
    for cand in candidates:
        if cand in all_files:
            return cand
    return None


def _extract_python_imports(
    source: bytes, tree, rel_path: str, all_files: set[str]
) -> set[str]:
    importer_dir = PurePosixPath(rel_path).parent
    found: set[str] = set()

    def visit(node: Node) -> None:
        if node.type == "import_statement":
            # import a.b.c [as x], d.e
            for child in node.named_children:
                target = child
                if child.type == "aliased_import":
                    target = child.child_by_field_name("name") or child
                if target.type == "dotted_name":
                    resolved = _resolve_py_dotted(
                        _node_text(source, target), importer_dir, all_files
                    )
                    if resolved:
                        found.add(resolved)
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            if module_node is None:
                return
            raw = _node_text(source, module_node)
            level = len(raw) - len(raw.lstrip("."))
            dotted = raw.lstrip(".")
            if level > 0:
                resolved = _resolve_py_relative(level, dotted, importer_dir, all_files)
                if resolved:
                    found.add(resolved)
                # from .mod import name → 也尝试 name 是子模块
                if dotted:
                    for name_node in node.named_children[1:]:
                        if name_node.type in {"dotted_name", "aliased_import"}:
                            t = name_node
                            if t.type == "aliased_import":
                                t = t.child_by_field_name("name") or t
                            sub = _resolve_py_relative(
                                level,
                                f"{dotted}.{_node_text(source, t)}",
                                importer_dir,
                                all_files,
                            )
                            if sub:
                                found.add(sub)
            else:
                resolved = _resolve_py_dotted(dotted, importer_dir, all_files)
                if resolved:
                    found.add(resolved)
                else:
                    # from a.b import c —— c 可能本身是模块
                    for name_node in node.named_children[1:]:
                        t = name_node
                        if t.type == "aliased_import":
                            t = t.child_by_field_name("name") or t
                        if t.type == "dotted_name":
                            sub = _resolve_py_dotted(
                                f"{dotted}.{_node_text(source, t)}",
                                importer_dir,
                                all_files,
                            )
                            if sub:
                                found.add(sub)
        for child in node.named_children:
            visit(child)

    visit(tree.root_node)
    return found


# ---------- JS / TS ----------

def _resolve_js_spec(
    spec: str, importer_dir: PurePosixPath, all_files: set[str]
) -> str | None:
    if spec.startswith("@/"):
        # 常见别名根：importer 向上找 src/ 或工程根
        rel = spec[2:]
        bases: list[str] = []
        cur = importer_dir
        while True:
            bases.extend([str(cur / "src"), str(cur)])
            if str(cur) in (".", ""):
                break
            cur = cur.parent
        for base in bases:
            prefix = "" if base == "." else base + "/"
            for suffix in [""] + JS_INDEX_CANDIDATES:
                cand = f"{prefix}{rel}{suffix}".lstrip("/")
                if cand in all_files:
                    return cand
        return None
    if not spec.startswith("."):
        return None  # 三方包
    resolved = PurePosixPath(
        str((importer_dir / spec)).replace("\\", "/")
    )
    # 规范化 ".." 段
    parts: list[str] = []
    for p in resolved.parts:
        if p == "..":
            if parts:
                parts.pop()
        elif p != ".":
            parts.append(p)
    base = "/".join(parts)
    for suffix in [""] + JS_INDEX_CANDIDATES:
        cand = base + suffix
        if cand in all_files:
            return cand
    return None


def _extract_js_imports(
    source: bytes, tree, rel_path: str, all_files: set[str]
) -> set[str]:
    importer_dir = PurePosixPath(rel_path).parent
    found: set[str] = set()

    def visit(node: Node) -> None:
        spec: str | None = None
        if node.type == "import_statement":
            src_node = node.child_by_field_name("source")
            if src_node is not None:
                spec = _node_text(source, src_node).strip("'\"`")
        elif node.type == "call_expression":
            fn = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            if (
                fn is not None
                and _node_text(source, fn) in {"require", "import"}
                and args is not None
                and args.named_children
                and args.named_children[0].type == "string"
            ):
                spec = _node_text(source, args.named_children[0]).strip("'\"`")
        elif node.type == "export_statement":
            src_node = node.child_by_field_name("source")
            if src_node is not None:
                spec = _node_text(source, src_node).strip("'\"`")
        if spec:
            resolved = _resolve_js_spec(spec, importer_dir, all_files)
            if resolved:
                found.add(resolved)
        for child in node.named_children:
            visit(child)

    visit(tree.root_node)
    return found


def extract_imports(
    repo_dir: Path, rel_path: Path, all_files: set[str]
) -> set[str]:
    """返回 rel_path 导入的仓库内文件相对路径集合（不含自身）。"""
    language = LANGUAGE_BY_EXT.get(rel_path.suffix.lower())
    if language is None:
        return set()
    try:
        source = (repo_dir / rel_path).read_bytes()
        tree = get_parser(language).parse(source)
    except Exception:
        return set()
    rel_str = str(rel_path)
    if language == "python":
        found = _extract_python_imports(source, tree, rel_str, all_files)
    else:
        found = _extract_js_imports(source, tree, rel_str, all_files)
    found.discard(rel_str)
    return found
