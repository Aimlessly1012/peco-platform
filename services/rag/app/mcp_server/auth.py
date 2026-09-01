"""MCP 可选鉴权（M4 D7）：MCP_AUTH_TOKEN 非空时校验 Bearer token。

写成纯 ASGI 中间件而不是 FastAPI 依赖——/mcp 是 mount 进来的子应用，
依赖注入进不去它的路由。
"""
import json
import logging
import secrets

logger = logging.getLogger(__name__)

UNAUTHORIZED_BODY = {
    "error": "MCP 鉴权失败：请在请求头携带 Authorization: Bearer <MCP_AUTH_TOKEN>",
    "hint": (
        'claude mcp add --transport http rag-coder <url> '
        '--header "Authorization: Bearer <token>"'
    ),
}


class MCPAuthMiddleware:
    """token 为空时完全透明（默认行为与 M3 一致）。"""

    def __init__(self, app, token: str = "", path: str = "/mcp") -> None:
        self.app = app
        self.token = token or ""
        self.path = path

    def _guards(self, scope) -> bool:
        """只拦 /mcp 与其子路径。注意不能用 startswith("/mcp")——
        那会把 /mcp-info（接入说明页的数据源，恰恰是用来告诉用户如何配 token 的）也拦掉。

        uvicorn --root-path 模式（子路径部署，M7）会把 root_path 拼进 scope["path"]
        （/mcp 变 /rag/api/mcp），匹配前先剥掉——生产鉴权被绕过就是这么来的。"""
        path = scope.get("path", "")
        root = scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root):] or "/"
        return path == self.path or path.startswith(self.path + "/")

    def _authorized(self, scope) -> bool:
        header = ""
        for key, value in scope.get("headers", ()):
            if key == b"authorization":
                header = value.decode("latin-1")
                break
        scheme, _, credential = header.partition(" ")
        if scheme.lower() != "bearer":
            return False
        # 常量时间比较：token 校验不该泄露前缀匹配长度
        return secrets.compare_digest(credential.strip(), self.token)

    async def __call__(self, scope, receive, send) -> None:
        if (
            not self.token
            or scope.get("type") != "http"
            or not self._guards(scope)
            or self._authorized(scope)
        ):
            await self.app(scope, receive, send)
            return

        logger.warning("拒绝未鉴权的 MCP 请求：%s", scope.get("path"))
        body = json.dumps(UNAUTHORIZED_BODY, ensure_ascii=False).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer realm="rag-coder-mcp"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
