"""服务元信息：MCP 接入说明数据源（M4 B11）+ 容量状态（M14）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.mcp_server.server import mcp

from app.services.auth.deps import require_user
from app.services.capacity import get_capacity

router = APIRouter(tags=["meta"], dependencies=[Depends(require_user)])


@router.get("/mcp-info")
async def mcp_info(request: Request):
    """MCP 接入信息：URL、是否需要鉴权、一键接入命令与工具清单。

    URL 按当前请求的 base_url 推导——容器内监听 8000、宿主映射 8001，
    写死端口会给出错误的接入命令。
    """
    mcp_url = str(request.base_url).rstrip("/") + "/mcp"
    auth_required = bool(settings.mcp_auth_token)

    command = f"claude mcp add --transport http rag-coder {mcp_url}"
    if auth_required:
        command += ' --header "Authorization: Bearer <MCP_AUTH_TOKEN>"'

    tools = await mcp.list_tools()
    return {
        "mcp_url": mcp_url,
        "transport": "streamable-http",
        "auth_required": auth_required,
        "auth_header": "Authorization: Bearer <MCP_AUTH_TOKEN>" if auth_required else None,
        "install_command": command,
        "tools": [
            {
                "name": tool.name,
                "description": (tool.description or "").strip().splitlines()[0],
            }
            for tool in tools
        ],
    }


@router.get("/meta/capacity")
async def capacity(session: AsyncSession = Depends(get_session)):
    """容量状态（M14）：槽位用量 + 磁盘剩余 + 是否还接受新项目。

    reason 只在 accepting=false 时非空，且已经是可直接展示的整句——
    前端拿到就渲染，不要再拼文案（design D3）。
    """
    return (await get_capacity(session)).as_dict()
