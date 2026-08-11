"""路由解析器：框架探测器链 → 功能模块划分（设计 D1）。

支持：Next.js（pages/app 文件路由）、React Router v6、Vue Router、FastAPI。
前后端按一级目录分区独立探测；全部失败降级为顶层目录分组（kind=dir）。
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

ROUTE_METHOD_RE = re.compile(
    r"@(?P<obj>\w+)\.(?P<method>get|post|put|delete|patch|head|options)\(\s*[\"'](?P<path>[^\"']*)[\"']"
)
INCLUDE_ROUTER_RE = re.compile(
    r"include_router\(\s*(?P<name>[\w.]+)(?:[^)]*?prefix\s*=\s*[\"'](?P<prefix>[^\"']*)[\"'])?"
)
APIROUTER_PREFIX_RE = re.compile(
    r"APIRouter\((?:[^)]*?prefix\s*=\s*[\"'](?P<prefix>[^\"']*)[\"'])?"
)
JSX_ROUTE_RE = re.compile(r"<Route\s[^>]*?path\s*=\s*[\"'](?P<path>[^\"']+)[\"']")
OBJ_PATH_RE = re.compile(r"[{,]\s*path\s*:\s*[\"'](?P<path>[^\"']+)[\"']")
DYNAMIC_IMPORT_RE = re.compile(r"import\(\s*[\"'](?P<spec>[^\"']+)[\"']\s*\)")


@dataclass
class BackendRoute:
    method: str          # GET / POST / ...
    path: str            # 含 prefix 的完整路径，如 /api/orders/{id}
    file: str            # 仓库内相对路径
    handler_symbol: str  # handler 函数名


@dataclass
class RouteModule:
    name: str
    kind: str            # page | api | dir | shared
    route_prefix: str
    entry_files: list[str] = field(default_factory=list)


@dataclass
class ModuleMap:
    modules: list[RouteModule] = field(default_factory=list)
    backend_routes: list[BackendRoute] = field(default_factory=list)
    fallback: bool = False


def _top_segment(route_path: str) -> str:
    segments = [s for s in route_path.split("/") if s and not s.startswith(("{", ":", "["))]
    return segments[0] if segments else "home"


def _sub_roots(files: list[str]) -> list[str]:
    roots = {""}
    for f in files:
        parts = f.split("/")
        if len(parts) > 1:
            roots.add(parts[0])
    return sorted(roots, key=lambda r: (r != "", r))


def _in_root(f: str, root: str) -> bool:
    return f.startswith(root + "/") if root else True


def _read(repo_files: dict[str, str], path: str) -> str:
    return repo_files.get(path, "")


# ---------- Next.js ----------

def _detect_nextjs(root: str, files: list[str], repo_files: dict[str, str]) -> list[RouteModule] | None:
    pkg_path = f"{root}/package.json" if root else "package.json"
    pkg_raw = _read(repo_files, pkg_path)
    if not pkg_raw:
        return None
    try:
        pkg = json.loads(pkg_raw)
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    except (json.JSONDecodeError, AttributeError):
        return None
    if "next" not in deps:
        return None

    prefix = f"{root}/" if root else ""
    groups: dict[str, list[tuple[str, str]]] = {}  # seg -> [(route, file)]
    for f in files:
        if not _in_root(f, root):
            continue
        rel = f[len(prefix):]
        for base in ("pages/", "src/pages/"):
            if rel.startswith(base):
                sub = rel[len(base):]
                stem = str(PurePosixPath(sub).with_suffix(""))
                if PurePosixPath(stem).name.startswith("_"):
                    break
                route = "/" + ("" if stem == "index" else re.sub(r"/index$", "", stem))
                seg = "api" if route.startswith("/api") else _top_segment(route)
                groups.setdefault(seg, []).append((route, f))
                break
        for base in ("app/", "src/app/"):
            if rel.startswith(base) and PurePosixPath(rel).name.split(".")[0] in {"page", "route", "layout"}:
                route = "/" + str(PurePosixPath(rel[len(base):]).parent)
                route = "/" if route == "/." else route
                seg = _top_segment(route)
                groups.setdefault(seg, []).append((route, f))
                break

    if not groups:
        return None
    modules = []
    for seg, items in sorted(groups.items()):
        kind = "api" if seg == "api" else "page"
        route_prefix = "/" + seg if seg != "home" else "/"
        modules.append(
            RouteModule(
                name=seg, kind=kind, route_prefix=route_prefix,
                entry_files=sorted({f for _, f in items}),
            )
        )
    return modules


# ---------- React Router v6 ----------

def _detect_react_router(root: str, files: list[str], repo_files: dict[str, str]) -> list[RouteModule] | None:
    config_files = []
    for f in files:
        if not _in_root(f, root) or not f.endswith((".tsx", ".jsx", ".ts", ".js")):
            continue
        src = _read(repo_files, f)
        if "createBrowserRouter(" in src or "<Route" in src:
            config_files.append(f)
    if not config_files:
        return None

    groups: dict[str, set[str]] = {}
    for cf in config_files:
        src = _read(repo_files, cf)
        paths = [m.group("path") for m in JSX_ROUTE_RE.finditer(src)]
        paths += [m.group("path") for m in OBJ_PATH_RE.finditer(src)]
        if not paths:
            continue
        for p in paths:
            groups.setdefault(_top_segment(p), set()).add(cf)
    if not groups:
        return None
    return [
        RouteModule(
            name=seg, kind="page",
            route_prefix="/" + seg if seg != "home" else "/",
            entry_files=sorted(fs),
        )
        for seg, fs in sorted(groups.items())
    ]


# ---------- Vue Router ----------

def _detect_vue_router(root: str, files: list[str], repo_files: dict[str, str]) -> list[RouteModule] | None:
    config_files = [
        f for f in files
        if _in_root(f, root) and f.endswith((".ts", ".js"))
        and ("createRouter(" in _read(repo_files, f) or "new VueRouter" in _read(repo_files, f))
    ]
    if not config_files:
        return None
    groups: dict[str, set[str]] = {}
    for cf in config_files:
        src = _read(repo_files, cf)
        importer_dir = PurePosixPath(cf).parent
        component_files: list[str] = []
        for m in DYNAMIC_IMPORT_RE.finditer(src):
            spec = m.group("spec")
            if spec.startswith("."):
                cand = str(importer_dir / spec).replace("../", "")
                component_files.append(cand)
        for m in OBJ_PATH_RE.finditer(src):
            seg = _top_segment(m.group("path"))
            groups.setdefault(seg, set()).add(cf)
            for comp in component_files:
                groups[seg].add(comp)
    if not groups:
        return None
    return [
        RouteModule(
            name=seg, kind="page",
            route_prefix="/" + seg if seg != "home" else "/",
            entry_files=sorted(fs),
        )
        for seg, fs in sorted(groups.items())
    ]


# ---------- FastAPI ----------

def _detect_fastapi(
    root: str, files: list[str], repo_files: dict[str, str]
) -> tuple[list[RouteModule], list[BackendRoute]] | None:
    route_files: dict[str, list[tuple[str, str, str]]] = {}  # file -> [(method, path, handler)]
    router_prefixes: dict[str, str] = {}  # file -> APIRouter(prefix=...)

    for f in files:
        if not _in_root(f, root) or not f.endswith(".py"):
            continue
        src = _read(repo_files, f)
        if not src:
            continue
        m_prefix = APIROUTER_PREFIX_RE.search(src)
        if m_prefix and m_prefix.group("prefix"):
            router_prefixes[f] = m_prefix.group("prefix")
        entries = []
        for m in ROUTE_METHOD_RE.finditer(src):
            after = src[m.end():]
            handler_m = re.search(r"\n\s*(?:async\s+)?def\s+(\w+)", after)
            handler = handler_m.group(1) if handler_m else "(unknown)"
            entries.append((m.group("method").upper(), m.group("path"), handler))
        if entries:
            route_files[f] = entries
    if not route_files:
        return None

    # include_router prefix：在含 FastAPI( 的入口文件中查 include_router，按被导入文件名模糊关联
    global_prefixes: dict[str, str] = {}  # route file -> prefix
    for f in files:
        if not _in_root(f, root) or not f.endswith(".py"):
            continue
        src = _read(repo_files, f)
        if "FastAPI(" not in src:
            continue
        import_map: dict[str, str] = {}  # alias -> module file hint
        for im in re.finditer(r"from\s+([\w.]+)\s+import\s+(\w+)(?:\s+as\s+(\w+))?", src):
            alias = im.group(3) or im.group(2)
            import_map[alias] = im.group(1).replace(".", "/")
        for m in INCLUDE_ROUTER_RE.finditer(src):
            name = m.group("name").split(".")[0]
            prefix = m.group("prefix") or ""
            hint = import_map.get(name, "")
            for rf in route_files:
                if hint and (rf.endswith(hint + ".py") or hint in rf):
                    global_prefixes[rf] = prefix

    backend_routes: list[BackendRoute] = []
    groups: dict[str, set[str]] = {}
    for rf, entries in route_files.items():
        full_prefix = global_prefixes.get(rf, "") + router_prefixes.get(rf, "")
        for method, path, handler in entries:
            full_path = (full_prefix + path) or "/"
            backend_routes.append(
                BackendRoute(method=method, path=full_path, file=rf, handler_symbol=handler)
            )
            seg_path = full_path[len(global_prefixes.get(rf, "")):] or full_path
            groups.setdefault(_top_segment(seg_path), set()).add(rf)

    modules = [
        RouteModule(
            name=seg, kind="api",
            route_prefix="/" + seg if seg != "home" else "/",
            entry_files=sorted(fs),
        )
        for seg, fs in sorted(groups.items())
    ]
    return modules, backend_routes


# ---------- 汇总入口 ----------

def parse_routes(files: list[str], repo_files: dict[str, str]) -> ModuleMap:
    """files: 可解析文件相对路径；repo_files: 相对路径 → 源码文本（含 package.json）。"""
    result = ModuleMap()
    seen_entry_owner: dict[str, str] = {}

    for root in _sub_roots(files):
        fe = (
            _detect_nextjs(root, files, repo_files)
            or _detect_react_router(root, files, repo_files)
            or _detect_vue_router(root, files, repo_files)
        )
        if fe:
            for mod in fe:
                key = f"page:{mod.name}"
                if key not in seen_entry_owner:
                    seen_entry_owner[key] = root
                    result.modules.append(mod)
        be = _detect_fastapi(root, files, repo_files)
        if be:
            mods, routes = be
            for mod in mods:
                key = f"api:{mod.name}"
                if key not in seen_entry_owner:
                    seen_entry_owner[key] = root
                    result.modules.append(mod)
            existing = {(r.method, r.path) for r in result.backend_routes}
            result.backend_routes.extend(
                r for r in routes if (r.method, r.path) not in existing
            )

    if not result.modules:
        # 降级：顶层目录分组（spec: 未知框架降级）
        result.fallback = True
        groups: dict[str, list[str]] = {}
        for f in files:
            top = f.split("/")[0] if "/" in f else "(root)"
            groups.setdefault(top, []).append(f)
        result.modules = [
            RouteModule(name=name, kind="dir", route_prefix="", entry_files=sorted(fs))
            for name, fs in sorted(groups.items())
        ]
    return result
