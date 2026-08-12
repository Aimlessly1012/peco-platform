"""路由解析器：框架探测器链 → 功能模块划分（设计 D1）。

支持：Next.js（pages/app 文件路由）、umi（约定式 src/pages + 配置式 routes 数组）、
React Router v6、FastAPI。前后端按一级目录分区独立探测。（Vue 明确不支持——用户不做 Vue 项目）
全部失败时两级降级（M4 B14）：页面目录感知分组 → 顶层目录分组（kind=dir）。
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

PAGE_EXTS = (".tsx", ".ts", ".jsx", ".js")

# 降级级别 1 识别的页面目录（相对各 root）。顺序即优先级
PAGE_DIR_MARKERS = ("src/pages", "src/views", "src/routes", "pages", "views", "app")

# umi 识别标志
UMI_DEPS = ("umi", "@umijs/max", "@umijs/preset-react", "@alipay/bigfish")
UMI_CONFIG_FILES = (
    ".umirc.ts", ".umirc.js", ".umirc.tsx",
    "config/routes.ts", "config/routes.js",
    "config/config.ts", "config/config.js",
)
UMI_NON_ROUTE_SEGMENTS = {"components", "component", "models", "services", "utils", "hooks", "locales"}

PROP_PATH_RE = re.compile(r"\bpath\s*:\s*[\"'](?P<value>[^\"']*)[\"']")
PROP_COMPONENT_RE = re.compile(r"\bcomponent\s*:\s*[\"'](?P<value>[^\"']+)[\"']")

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


# ---------- umi ----------

def _package_deps(root: str, repo_files: dict[str, str]) -> dict:
    pkg_raw = _read(repo_files, f"{root}/package.json" if root else "package.json")
    if not pkg_raw:
        return {}
    try:
        pkg = json.loads(pkg_raw)
        return {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    except (json.JSONDecodeError, AttributeError):
        return {}


def _umi_config_paths(root: str) -> list[str]:
    return [f"{root}/{name}" if root else name for name in UMI_CONFIG_FILES]


def _is_umi_project(root: str, repo_files: dict[str, str]) -> bool:
    """依赖含 umi/@umijs/max，或存在 .umirc / config 路由文件（spec 识别标志）。"""
    if any(dep in _package_deps(root, repo_files) for dep in UMI_DEPS):
        return True
    return any(_read(repo_files, p) for p in _umi_config_paths(root))


def _umi_dynamic_segment(segment: str) -> str:
    """umi 动态段：[id] / $id → :id；[...rest] / $ → 通配。"""
    if segment.startswith("[") and segment.endswith("]"):
        inner = segment[1:-1]
        return "*" if inner.startswith("...") else f":{inner}"
    if segment == "$":
        return "*"
    if segment.startswith("$"):
        return f":{segment[1:]}"
    return segment


def _umi_convention_routes(root: str, files: list[str]) -> list[tuple[str, str]]:
    """约定式：src/pages 下的文件即路由（_ 开头与 components 等目录不算）。"""
    base = f"{root}/src/pages/" if root else "src/pages/"
    routes: list[tuple[str, str]] = []
    for f in files:
        if not f.startswith(base):
            continue
        sub = PurePosixPath(f[len(base):])
        if sub.suffix not in PAGE_EXTS or sub.name.endswith(".d.ts"):
            continue
        stem = sub.with_suffix("")
        segments = list(stem.parts)
        name = segments[-1]
        if any(s.startswith("_") for s in segments):
            continue  # _layout / _404 等约定文件不是路由
        if any(s in UMI_NON_ROUTE_SEGMENTS for s in segments[:-1]):
            continue
        if ".test" in name or ".spec" in name:
            continue
        route_segments = [
            _umi_dynamic_segment(s) for s in segments if s != "index"
        ]
        route = "/" + "/".join(route_segments)
        routes.append((route.rstrip("/") or "/", f))
    return routes


def _iter_object_blocks(text: str):
    """产出源码中每一个花括号平衡块（含嵌套块本身），用于逐个对象读属性。"""
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            yield text[start : i + 1]


def _own_props(block: str) -> str:
    """只保留本层属性文本，剔除嵌套对象——否则父路由会读到子路由的 path。"""
    out: list[str] = []
    depth = 0
    for ch in block[1:-1]:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _resolve_umi_component(spec: str, root: str, file_set: set[str]) -> str | None:
    """component: '@/pages/users' → 仓库内真实文件（@ 映射 src）。"""
    rel = spec.strip()
    if rel.startswith("@/"):
        rel = "src/" + rel[2:]
    else:
        rel = rel.lstrip("./")
    prefix = f"{root}/" if root else ""
    candidates = [f"{prefix}{rel}"]
    candidates += [f"{prefix}{rel}{ext}" for ext in PAGE_EXTS]
    candidates += [f"{prefix}{rel}/index{ext}" for ext in PAGE_EXTS]
    return next((c for c in candidates if c in file_set), None)


def _umi_config_routes(
    root: str, files: list[str], repo_files: dict[str, str]
) -> list[tuple[str, str]]:
    """配置式：.umirc.ts / config/routes.ts 的 routes 数组（component 解析为入口文件）。"""
    file_set = set(files)
    routes: list[tuple[str, str]] = []
    for config_path in _umi_config_paths(root):
        src = _read(repo_files, config_path)
        if not src:
            continue
        for block in _iter_object_blocks(src):
            props = _own_props(block)
            component = PROP_COMPONENT_RE.search(props)
            if component is None:
                continue
            entry = _resolve_umi_component(component.group("value"), root, file_set)
            if entry is None:
                continue
            path_match = PROP_PATH_RE.search(props)
            route = (path_match.group("value") if path_match else "") or "/"
            routes.append((route if route.startswith("/") else f"/{route}", entry))
    return routes


def _detect_umi(
    root: str, files: list[str], repo_files: dict[str, str]
) -> list[RouteModule] | None:
    if not _is_umi_project(root, repo_files):
        return None
    # umi 配置了 routes 时约定式路由自动失效，故配置式优先
    routes = _umi_config_routes(root, files, repo_files)
    if not routes:
        routes = _umi_convention_routes(root, files)
    if not routes:
        return None

    groups: dict[str, set[str]] = {}
    for route, entry in routes:
        groups.setdefault(_top_segment(route), set()).add(entry)
    return [
        RouteModule(
            name=seg, kind="page",
            route_prefix="/" + seg if seg != "home" else "/",
            entry_files=sorted(fs),
        )
        for seg, fs in sorted(groups.items())
    ]


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


# ---------- 降级分组（M4 B14） ----------

def _page_dir_modules(files: list[str]) -> list[RouteModule]:
    """降级级别 1：存在页面目录时，以其下一级子目录/文件为模块。

    比顶层目录分组有信息量得多——src 集中式仓库降级后至少还能按业务页面切开，
    而不是产出一个 src 巨模块。
    """
    for marker in PAGE_DIR_MARKERS:
        groups: dict[str, list[str]] = {}
        needle = f"/{marker}/"
        for f in files:
            if f.startswith(f"{marker}/"):
                rest = f[len(marker) + 1:]
            elif needle in f:
                rest = f.split(needle, 1)[1]
            else:
                continue
            head = rest.split("/", 1)
            name = head[0] if len(head) > 1 else PurePosixPath(head[0]).stem
            if name.startswith("_") or not name:
                continue
            groups.setdefault(name, []).append(f)
        if len(groups) >= 2:
            return [
                RouteModule(name=name, kind="page", route_prefix="", entry_files=sorted(fs))
                for name, fs in sorted(groups.items())
            ]
    return []


def _top_dir_modules(files: list[str]) -> list[RouteModule]:
    """降级级别 2：顶层目录分组（M1 起的兜底行为）。"""
    groups: dict[str, list[str]] = {}
    for f in files:
        top = f.split("/")[0] if "/" in f else "(root)"
        groups.setdefault(top, []).append(f)
    return [
        RouteModule(name=name, kind="dir", route_prefix="", entry_files=sorted(fs))
        for name, fs in sorted(groups.items())
    ]


# ---------- 汇总入口 ----------

def parse_routes(files: list[str], repo_files: dict[str, str]) -> ModuleMap:
    """files: 可解析文件相对路径；repo_files: 相对路径 → 源码文本（含 package.json）。"""
    result = ModuleMap()
    seen_entry_owner: dict[str, str] = {}

    for root in _sub_roots(files):
        fe = (
            _detect_nextjs(root, files, repo_files)
            # umi 排在 react-router 之前：umi 基于 react-router，其配置里的 path:
            # 会被 react-router 探测器误抓成"配置文件即入口"，模块划分退化
            or _detect_umi(root, files, repo_files)
            or _detect_react_router(root, files, repo_files)
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
        # 两级降级（M4 B14）：页面目录感知 → 顶层目录
        result.fallback = True
        result.modules = _page_dir_modules(files) or _top_dir_modules(files)
    return result
