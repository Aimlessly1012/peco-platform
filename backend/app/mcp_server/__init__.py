"""MCP 服务（M3 设计 D4/D5）：官方 python SDK streamable-http，与 FastAPI 同进程。"""
from app.mcp_server.server import mcp, mcp_http_app

__all__ = ["mcp", "mcp_http_app"]
