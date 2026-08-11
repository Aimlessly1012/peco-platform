"""M3 MCP 服务单测（B6）：挂载冒烟（initialize + tools/list）与七工具契约。

走真实 ASGI 路径 POST /mcp（含 streamable-http 的 SSE 响应与 session 头），
只把 Neo4j 读取与向量检索打桩，因此挂载方式、lifespan 合并、DNS 防护都被真实覆盖。
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.models.tables import Project, ProjectStatus, UnderstandingReport
from app.services.report.graph_reader import ProjectTree
from app.services.retrieval.service import RetrievedItem
from tests.test_report import make_tree

TOOL_NAMES = {
    "list_projects",
    "get_project_overview",
    "get_module_map",
    "search_code",
    "get_file_summary",
    "impact_analysis",
    "get_project_understanding",
}

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _parse_sse(text: str) -> dict:
    """streamable-http 的响应体是 SSE：取 data: 行的 JSON。"""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    raise AssertionError(f"响应中没有 SSE data 行：{text[:200]}")


class MCPSession:
    """极简 MCP 客户端：够用来验证握手与工具调用契约。"""

    def __init__(self, client: AsyncClient):
        self.client = client
        self.session_id: str | None = None
        self._id = 0

    async def request(self, method: str, params: dict | None = None):
        self._id += 1
        headers = dict(HEADERS)
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        body = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            body["params"] = params
        resp = await self.client.post("/mcp", json=body, headers=headers)
        assert resp.status_code == 200, f"{method} -> {resp.status_code}: {resp.text[:300]}"
        if "mcp-session-id" in resp.headers:
            self.session_id = resp.headers["mcp-session-id"]
        return _parse_sse(resp.text)

    async def notify(self, method: str) -> None:
        headers = dict(HEADERS)
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        resp = await self.client.post(
            "/mcp", json={"jsonrpc": "2.0", "method": method}, headers=headers
        )
        assert resp.status_code in (200, 202), resp.text[:300]

    async def initialize(self) -> dict:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        )
        await self.notify("notifications/initialized")
        return result

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """返回工具的结构化输出（structuredContent）。"""
        payload = await self.request(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        assert "error" not in payload, payload  # 协议级错误 = 连接层面出问题
        result = payload["result"]
        if "structuredContent" in result:
            return result["structuredContent"]
        return json.loads(result["content"][0]["text"])


@pytest.fixture
async def mcp_session(test_db, monkeypatch):
    """真实跑 FastAPI lifespan（含 MCP session manager），仅打桩 Neo4j 启动检查。

    lifespan 必须在同一个 task 里进出——MCP session manager 内部是 anyio task group，
    跨 task 退出会触发 "cancel scope in a different task"（pytest fixture 的
    setup/teardown 分属不同 task），所以用一个常驻 runner task 持有它。
    """

    async def noop():
        return None

    monkeypatch.setattr("app.main.ensure_vector_index", noop)
    monkeypatch.setattr("app.main.close_driver", noop)

    from app.main import create_app

    app = create_app()  # 每个测试一套全新的 MCP session manager（run() 不可复用）
    started, stop = asyncio.Event(), asyncio.Event()

    async def runner():
        async with app.router.lifespan_context(app):
            started.set()
            await stop.wait()

    task = asyncio.create_task(runner())
    # runner 若在启动阶段抛错，不能在这里静默挂死
    done, _ = await asyncio.wait(
        [asyncio.create_task(started.wait()), task],
        return_when=asyncio.FIRST_COMPLETED,
        timeout=30,
    )
    if task in done:
        task.result()  # 抛出 runner 的异常
        raise AssertionError("lifespan 提前退出")
    assert started.is_set(), "lifespan 启动超时"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8001") as client:
        session = MCPSession(client)
        await session.initialize()
        yield session

    stop.set()
    await task


# ---------------- 挂载冒烟（先跑通这两个，再展开工具） ----------------


async def test_mcp_initialize_handshake(mcp_session):
    """spec 场景: MCP 客户端对 /mcp 发起 initialize → 返回服务器信息。"""
    result = await mcp_session.request(
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {},
         "clientInfo": {"name": "pytest", "version": "0"}},
    )
    info = result["result"]["serverInfo"]
    assert info["name"] == "rag-coder"
    assert result["result"]["capabilities"]["tools"] is not None


async def test_mcp_lists_seven_tools(mcp_session):
    """spec 场景: 返回 7 个工具的定义清单。"""
    result = await mcp_session.request("tools/list")
    tools = result["result"]["tools"]
    assert {t["name"] for t in tools} == TOOL_NAMES
    assert len(tools) == 7
    # 每个工具都要有中文说明（agent 靠它选工具）
    assert all(t.get("description") for t in tools)
    search = next(t for t in tools if t["name"] == "search_code")
    assert set(search["inputSchema"]["properties"]) == {"project", "query", "module", "top_k"}
    assert search["inputSchema"]["required"] == ["project", "query"]


async def test_fastapi_routes_still_work_under_root_mount(mcp_session):
    """MCP 挂在根路径，业务路由与 API 文档必须仍然优先匹配。"""
    resp = await mcp_session.client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    schema = await mcp_session.client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/projects/{project_id}/report" in paths
    assert "/projects/{project_id}/modules" in paths


async def test_dns_rebinding_protection_rejects_foreign_host(mcp_session):
    """MCP 无鉴权，非本机 Host 必须被拒（防浏览器端 DNS 重绑定读取代码库）。"""
    resp = await mcp_session.client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 99, "method": "tools/list"},
        headers={**HEADERS, "Host": "evil.example.com"},
    )
    assert resp.status_code == 421


# ---------------- 项目数据与图打桩 ----------------


async def _add_project(test_db, name="mini-shop", status=ProjectStatus.READY) -> uuid.UUID:
    async with test_db() as session:
        project = Project(name=name, git_url="https://example.com/x.git", status=status)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project.id


@pytest.fixture
def stub_graph(monkeypatch):
    """打桩 server 命名空间里的图读取与检索。"""
    state = {
        "tree": make_tree(),
        "stats": {"modules_count": 4, "languages": ["python", "typescript"]},
        "file_detail": {
            "path": "backend/routers/orders.py",
            "language": "python",
            "summary": "订单路由：创建与查询订单",
            "symbols": [{"name": "create_order", "type": "function", "lines": "40-58"}],
            "imports": ["backend/services/order_service.py"],
            "imported_by": ["backend/main.py"],
            "modules": ["api:orders"],
        },
        "impact": {
            "imported_by": [{"file_path": "backend/main.py", "summary": "应用入口"}],
            "api_callers": [
                {
                    "file_path": "frontend/pages/orders.tsx", "symbol": "OrdersPage",
                    "lines": "5-30", "calls_handler": "create_order",
                }
            ],
            "modules_affected": [
                {"name": "orders", "kind": "api", "route_prefix": "/api/orders"}
            ],
        },
        "symbol_files": ["backend/routers/orders.py"],
        "search": [
            RetrievedItem(
                kind="chunk", node_id="n1", file_path="backend/routers/orders.py",
                symbol="create_order", symbol_type="function",
                start_line=40, end_line=58,
                content="\n".join(f"line {i}" for i in range(200)),  # 200 行，用于验证截断
                score=0.9,
            ),
            RetrievedItem(
                kind="chunk", node_id="n2", file_path="frontend/pages/orders.tsx",
                symbol="OrdersPage", symbol_type="component",
                start_line=5, end_line=30, content="export default function OrdersPage() {}",
                score=0.8, via_edge="calls_api",
            ),
        ],
    }

    async def fake_tree(pid: str):
        return state["tree"]

    async def fake_stats(pid: str):
        return state["stats"]

    async def fake_file_detail(pid: str, path: str):
        detail = state["file_detail"]
        return detail if detail and detail["path"] == path else None

    async def fake_impact(pid: str, path: str):
        return state["impact"]

    async def fake_symbol_files(pid: str, symbol: str):
        return state["symbol_files"]

    async def fake_search(pid: str, query: str, question_type: str = "local", top_k=None):
        return state["search"]

    monkeypatch.setattr("app.mcp_server.server.read_project_tree", fake_tree)
    monkeypatch.setattr("app.mcp_server.server.read_project_stats", fake_stats)
    monkeypatch.setattr("app.mcp_server.server.read_file_detail", fake_file_detail)
    monkeypatch.setattr("app.mcp_server.server.read_impact", fake_impact)
    monkeypatch.setattr("app.mcp_server.server.resolve_symbol_files", fake_symbol_files)
    monkeypatch.setattr("app.mcp_server.server.search_layered", fake_search)
    return state


# ---------------- 工具契约（D5） ----------------


async def test_list_projects(mcp_session, test_db, stub_graph):
    await _add_project(test_db, "mini-shop")
    await _add_project(test_db, "half-done", status=ProjectStatus.INDEXING)

    out = await mcp_session.call_tool("list_projects")

    assert out["count"] == 2
    by_name = {p["name"]: p for p in out["projects"]}
    assert by_name["mini-shop"]["modules_count"] == 4
    assert by_name["mini-shop"]["languages"] == ["python", "typescript"]
    assert uuid.UUID(by_name["mini-shop"]["id"])
    # 未就绪项目不查图，计数为 0 但仍列出（agent 能看到它存在）
    assert by_name["half-done"]["status"] == "indexing"
    assert by_name["half-done"]["modules_count"] == 0


async def test_get_project_overview_by_name_and_id(mcp_session, test_db, stub_graph):
    pid = await _add_project(test_db)

    by_name = await mcp_session.call_tool("get_project_overview", {"project": "mini-shop"})
    by_id = await mcp_session.call_tool("get_project_overview", {"project": str(pid)})

    assert by_name["resolved_project_id"] == str(pid) == by_id["resolved_project_id"]
    assert by_name["summary"] == "全栈演示项目：订单与用户"
    orders = next(m for m in by_name["modules"] if m["kind"] == "api" and m["name"] == "orders")
    assert orders["prefix"] == "/api/orders"
    assert orders["summary_head"].startswith("订单接口模块")
    assert orders["files_count"] == 2


async def test_duplicate_name_resolves_to_newest(mcp_session, test_db, stub_graph):
    """设计 D5: 重名取最新创建者，并在返回中带 resolved_project_id。"""
    old = await _add_project(test_db, "dup")
    new = await _add_project(test_db, "dup")
    assert old != new

    out = await mcp_session.call_tool("get_project_overview", {"project": "dup"})
    assert out["resolved_project_id"] == str(new)


async def test_get_module_map(mcp_session, test_db, stub_graph):
    await _add_project(test_db)
    out = await mcp_session.call_tool("get_module_map", {"project": "mini-shop"})

    assert out["mermaid_mindmap"].startswith("mindmap")
    orders = next(m for m in out["modules"] if m["name"] == "orders" and m["kind"] == "api")
    assert "backend/routers/orders.py" in orders["files"]


async def test_search_code_contract(mcp_session, test_db, stub_graph):
    """spec 场景: 返回 ≤top_k 条，各含 file_path、行号区间、symbol 与片段。"""
    await _add_project(test_db)
    out = await mcp_session.call_tool(
        "search_code", {"project": "mini-shop", "query": "订单创建逻辑", "top_k": 5}
    )

    assert out["count"] <= 5
    first = out["results"][0]
    assert first["file_path"] == "backend/routers/orders.py"
    assert first["lines"] == "40-58"
    assert first["symbol"] == "create_order"
    assert first["symbol_type"] == "function"
    # 代码片段截断 80 行
    assert first["snippet"].count("\n") <= 80
    assert "已截断" in first["snippet"]
    assert out["results"][1]["via_edge"] == "calls_api"


async def test_search_code_clamps_top_k(mcp_session, test_db, stub_graph, monkeypatch):
    """spec: top_k 上限 20。"""
    await _add_project(test_db)
    seen = {}

    async def spy_search(pid, query, question_type="local", top_k=None):
        seen["top_k"] = top_k
        return []

    monkeypatch.setattr("app.mcp_server.server.search_layered", spy_search)
    await mcp_session.call_tool(
        "search_code", {"project": "mini-shop", "query": "x", "top_k": 500}
    )
    assert seen["top_k"] == 20


async def test_search_code_module_filter(mcp_session, test_db, stub_graph):
    await _add_project(test_db)
    out = await mcp_session.call_tool(
        "search_code", {"project": "mini-shop", "query": "订单", "module": "orders"}
    )
    # orders 模块（api+page）覆盖两个命中文件
    assert out["count"] == 2

    missing = await mcp_session.call_tool(
        "search_code", {"project": "mini-shop", "query": "订单", "module": "不存在的模块"}
    )
    assert "没有名为" in missing["error"]
    assert "orders" in missing["available_modules"]


async def test_search_code_rejects_empty_query(mcp_session, test_db, stub_graph):
    await _add_project(test_db)
    out = await mcp_session.call_tool(
        "search_code", {"project": "mini-shop", "query": "   "}
    )
    assert "query" in out["error"]


async def test_get_file_summary(mcp_session, test_db, stub_graph):
    pid = await _add_project(test_db)
    out = await mcp_session.call_tool(
        "get_file_summary",
        {"project": "mini-shop", "path": "backend/routers/orders.py"},
    )

    assert out["resolved_project_id"] == str(pid)
    assert out["summary"].startswith("订单路由")
    assert out["symbols"][0] == {"name": "create_order", "type": "function", "lines": "40-58"}
    assert out["imports"] == ["backend/services/order_service.py"]
    assert out["imported_by"] == ["backend/main.py"]


async def test_get_file_summary_missing_file(mcp_session, test_db, stub_graph):
    await _add_project(test_db)
    out = await mcp_session.call_tool(
        "get_file_summary", {"project": "mini-shop", "path": "no/such.py"}
    )
    assert "没有文件" in out["error"]
    assert "hint" in out


async def test_impact_analysis_by_path(mcp_session, test_db, stub_graph):
    """spec 场景: 返回 import 它的文件、经 CALLS_API 调它的前端块及所属模块。"""
    await _add_project(test_db)
    out = await mcp_session.call_tool(
        "impact_analysis",
        {"project": "mini-shop", "file_or_symbol": "backend/routers/orders.py"},
    )

    assert out["resolved_files"] == ["backend/routers/orders.py"]
    assert out["imported_by"][0]["file_path"] == "backend/main.py"
    assert out["api_callers"][0]["file_path"] == "frontend/pages/orders.tsx"
    assert out["api_callers"][0]["calls_handler"] == "create_order"
    assert out["modules_affected"][0]["name"] == "orders"


async def test_impact_analysis_by_symbol(mcp_session, test_db, stub_graph):
    await _add_project(test_db)
    out = await mcp_session.call_tool(
        "impact_analysis", {"project": "mini-shop", "file_or_symbol": "create_order"}
    )
    assert out["resolved_files"] == ["backend/routers/orders.py"]


async def test_impact_analysis_unknown_target(mcp_session, test_db, stub_graph):
    await _add_project(test_db)
    stub_graph["symbol_files"] = []
    out = await mcp_session.call_tool(
        "impact_analysis", {"project": "mini-shop", "file_or_symbol": "nope"}
    )
    assert "找不到文件或符号" in out["error"]


async def test_get_project_understanding(mcp_session, test_db, stub_graph):
    pid = await _add_project(test_db)
    async with test_db() as session:
        session.add(
            UnderstandingReport(
                project_id=pid, doc_markdown="# 需求逻辑文档",
                mindmap_mermaid="mindmap\n  root((x))",
                sequences_json=[{"module_key": "api:orders", "module_name": "orders",
                                 "mermaid": "sequenceDiagram", "fallback_text": ""}],
                generated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    out = await mcp_session.call_tool(
        "get_project_understanding", {"project": "mini-shop"}
    )
    assert out["doc_markdown"] == "# 需求逻辑文档"
    assert out["mindmap_mermaid"].startswith("mindmap")
    assert out["sequences"][0]["module_key"] == "api:orders"
    assert out["generated_at"]


async def test_get_project_understanding_without_report(mcp_session, test_db, stub_graph):
    await _add_project(test_db)
    out = await mcp_session.call_tool(
        "get_project_understanding", {"project": "mini-shop"}
    )
    assert "还没有理解报告" in out["error"]
    assert "重新索引" in out["hint"]


# ---------------- 错误与隔离契约 ----------------


async def test_not_ready_project_returns_error_and_keeps_connection(
    mcp_session, test_db, stub_graph
):
    """spec 场景: indexing 状态调 search_code → 错误文本，连接保持可用。"""
    await _add_project(test_db, "building", status=ProjectStatus.INDEXING)

    out = await mcp_session.call_tool(
        "search_code", {"project": "building", "query": "订单"}
    )
    assert "索引未完成" in out["error"]
    assert out["status"] == "indexing"
    assert "稍后重试" in out["hint"]

    # 同一连接继续可用
    still = await mcp_session.request("tools/list")
    assert len(still["result"]["tools"]) == 7


@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_project_overview", {}),
        ("get_module_map", {}),
        ("search_code", {"query": "x"}),
        ("get_file_summary", {"path": "a.py"}),
        ("impact_analysis", {"file_or_symbol": "a.py"}),
        ("get_project_understanding", {}),
    ],
)
async def test_unknown_project_returns_structured_error(
    mcp_session, test_db, stub_graph, tool, args
):
    await _add_project(test_db, "mini-shop")
    out = await mcp_session.call_tool(tool, {"project": "不存在的项目", **args})

    assert "未找到项目" in out["error"]
    assert "mini-shop" in out["available_projects"]
    assert "list_projects" in out["hint"]


async def test_empty_project_arg_rejected(mcp_session, test_db, stub_graph):
    out = await mcp_session.call_tool("get_project_overview", {"project": "  "})
    assert "不能为空" in out["error"]


async def test_queries_are_isolated_by_resolved_project_id(
    mcp_session, test_db, monkeypatch
):
    """spec: 所有查询 MUST 按解析后的 project_id 过滤。"""
    pid = await _add_project(test_db, "mini-shop")
    other = await _add_project(test_db, "other-project")
    seen: list[str] = []

    async def spy_tree(project_id: str):
        seen.append(project_id)
        return ProjectTree(project_id=project_id, name="mini-shop")

    monkeypatch.setattr("app.mcp_server.server.read_project_tree", spy_tree)
    await mcp_session.call_tool("get_project_overview", {"project": "mini-shop"})

    assert seen == [str(pid)]
    assert str(other) not in seen
