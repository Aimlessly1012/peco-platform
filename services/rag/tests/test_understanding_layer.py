"""M2 解析层单测：IMPORTS / 路由探测 / 文件归属 / CALLS_API（用 mini_repo fixture）。"""
from pathlib import Path

from app.services.ingest.api_matcher import extract_api_edges
from app.services.ingest.chunker import chunk_file
from app.services.ingest.deps_extractor import extract_imports
from app.services.ingest.module_mapper import assign_files
from app.services.ingest.router_parser import parse_routes
from app.services.ingest.walker import walk_repo

FIXTURE = Path(__file__).parent / "fixtures" / "mini_repo"


def _load_repo():
    walk = walk_repo(FIXTURE)
    files = [str(f) for f in walk.files]
    repo_files = {f: (FIXTURE / f).read_text(encoding="utf-8") for f in files}
    # 路由探测还需要 package.json 等清单
    for extra in FIXTURE.rglob("package.json"):
        rel = str(extra.relative_to(FIXTURE))
        repo_files[rel] = extra.read_text(encoding="utf-8")
    return files, repo_files


def test_python_imports_resolved():
    files, _ = _load_repo()
    targets = extract_imports(
        FIXTURE, Path("backend/routers/orders.py"), set(files)
    )
    assert "backend/services/order_service.py" in targets


def test_ts_imports_resolved():
    files, _ = _load_repo()
    targets = extract_imports(FIXTURE, Path("frontend/pages/orders.tsx"), set(files))
    assert "frontend/components/OrderCard.tsx" in targets
    assert "frontend/lib/api.ts" in targets


def test_parse_routes_fullstack():
    files, repo_files = _load_repo()
    result = parse_routes(files, repo_files)
    assert result.fallback is False
    kinds = {m.kind for m in result.modules}
    assert "page" in kinds and "api" in kinds  # spec: 全栈仓库产出两类模块

    api_orders = next(m for m in result.modules if m.kind == "api" and m.name == "orders")
    assert "backend/routers/orders.py" in api_orders.entry_files

    paths = {(r.method, r.path) for r in result.backend_routes}
    assert ("GET", "/api/orders") in paths  # include_router prefix 拼接正确
    assert ("DELETE", "/api/orders/{order_id}") in paths


def test_fallback_on_unknown_framework(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "util.py").write_text("def helper():\n    return 1\n")
    files = ["core/util.py"]
    repo_files = {f: (tmp_path / f).read_text() for f in files}
    result = parse_routes(files, repo_files)
    assert result.fallback is True  # spec: 未知框架降级
    assert result.modules[0].kind == "dir"


def test_file_assignment():
    files, repo_files = _load_repo()
    module_map = parse_routes(files, repo_files)
    imports = {f: extract_imports(FIXTURE, Path(f), set(files)) for f in files}
    assignment = assign_files(files, module_map, imports)

    # 服务层文件经 IMPORTS 归属 orders 接口模块（键为 kind:name）
    assert "api:orders" in assignment["backend/services/order_service.py"]
    # 组件经页面 import 归属 orders 页面模块
    assert "page:orders" in assignment["frontend/components/OrderCard.tsx"]
    # 每个文件都有归属（shared 兜底）
    assert all(mods for mods in assignment.values())


def test_calls_api_edges():
    files, repo_files = _load_repo()
    module_map = parse_routes(files, repo_files)
    all_chunks = []
    for f in files:
        all_chunks.extend(chunk_file(FIXTURE, Path(f)))
    by_key = {(c.file_path, c.symbol): c for c in all_chunks}
    frontend_chunks = [c for c in all_chunks if c.language in {"tsx", "typescript", "javascript"}]

    edges, warnings = extract_api_edges(frontend_chunks, module_map.backend_routes, by_key)

    pairs = {(e.source_file, e.target_symbol) for e in edges}
    # spec: orders.tsx 的 apiGet("/api/orders") ↔ 后端 GET /api/orders handler
    assert ("frontend/pages/orders.tsx", "list_orders") in pairs
    assert ("frontend/pages/orders.tsx", "create_order") in pairs
