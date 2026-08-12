"""MCP 可选鉴权与接入信息端点（M4 B11）。"""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.mcp_server.auth import MCPAuthMiddleware

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "pytest", "version": "0"}},
}


@pytest.fixture
def authed_app(monkeypatch, test_db):
    """开启鉴权的 app（不进 lifespan：401 必须在 MCP session manager 之前就拦掉）。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "mcp_auth_token", "s3cret-token")

    async def noop():
        return None

    monkeypatch.setattr("app.main.ensure_vector_index", noop)
    monkeypatch.setattr("app.main.close_driver", noop)

    from app.main import create_app

    return create_app()


async def client_for(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8001")


async def test_missing_token_rejected(authed_app):
    """spec 场景: 已设置 token 但请求未带 Authorization → 401，不泄露项目数据。"""
    async with await client_for(authed_app) as client:
        resp = await client.post("/mcp", json=INIT, headers=HEADERS)

    assert resp.status_code == 401
    body = resp.json()
    assert "鉴权失败" in body["error"]
    assert "Bearer" in body["hint"]
    assert resp.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.parametrize(
    "value",
    [
        "wrong-token",
        "Bearer wrong-token",
        "Basic s3cret-token",
        "Bearer s3cret",          # 前缀匹配不算通过
        "Bearer s3cret-token-x",  # 更长也不行
        "",
    ],
)
async def test_bad_credentials_rejected(authed_app, value):
    async with await client_for(authed_app) as client:
        resp = await client.post(
            "/mcp", json=INIT, headers={**HEADERS, "Authorization": value}
        )
    assert resp.status_code == 401


async def test_business_routes_not_affected_by_mcp_auth(authed_app):
    """鉴权只拦 /mcp，后台自身的 API 不受影响。"""
    async with await client_for(authed_app) as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/mcp-info")).status_code == 200


async def test_valid_token_passes_through(authed_app, monkeypatch):
    """带正确 token 时中间件放行（放行后交给 MCP 子应用处理）。"""
    seen = {}

    async def fake_downstream(scope, receive, send):
        seen["path"] = scope["path"]
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = MCPAuthMiddleware(fake_downstream, token="s3cret-token")
    scope = {
        "type": "http", "path": "/mcp", "method": "POST",
        "headers": [(b"authorization", b"Bearer s3cret-token")],
    }
    sent = []

    async def send(message):
        sent.append(message)

    await middleware(scope, None, send)

    assert seen["path"] == "/mcp"
    assert sent[0]["status"] == 204


async def test_disabled_by_default(test_db, monkeypatch):
    """spec 场景: MCP_AUTH_TOKEN 为空时行为与 M3 完全一致（无需客户端改动）。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "mcp_auth_token", "")

    calls = []

    async def downstream(scope, receive, send):
        calls.append(scope["path"])

    middleware = MCPAuthMiddleware(downstream, token=settings.mcp_auth_token)
    await middleware({"type": "http", "path": "/mcp", "headers": []}, None, None)

    assert calls == ["/mcp"]


async def test_non_http_scope_passes_through():
    calls = []

    async def downstream(scope, receive, send):
        calls.append(scope["type"])

    middleware = MCPAuthMiddleware(downstream, token="x")
    await middleware({"type": "lifespan", "path": "/mcp", "headers": []}, None, None)

    assert calls == ["lifespan"]


# ---------------- GET /mcp-info ----------------


async def test_mcp_info_without_auth(api_client):
    resp = await api_client.get("/mcp-info")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mcp_url"] == "http://localhost:8001/mcp"  # 按请求 base_url 推导
    assert body["transport"] == "streamable-http"
    assert body["auth_required"] is False
    assert body["auth_header"] is None
    assert body["install_command"] == (
        "claude mcp add --transport http rag-coder http://localhost:8001/mcp"
    )
    names = {tool["name"] for tool in body["tools"]}
    assert len(names) == 7
    assert "impact_analysis" in names
    assert all(tool["description"] for tool in body["tools"])


async def test_mcp_info_with_auth(api_client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "mcp_auth_token", "s3cret-token")
    body = (await api_client.get("/mcp-info")).json()

    assert body["auth_required"] is True
    assert "--header" in body["install_command"]
    assert "Authorization: Bearer" in body["install_command"]
    # 不回显真实 token（说明页是公开的）
    assert "s3cret-token" not in json.dumps(body)
