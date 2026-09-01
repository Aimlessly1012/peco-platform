"""project 参数解析与结构化错误（设计 D5）。

agent 传项目名或 uuid 都可；重名取最新创建者，返回中带 resolved_project_id。
所有失败一律返回错误 dict（不抛异常），保证 MCP 连接不中断（spec: MCP 错误与隔离契约）。
"""
import uuid

from sqlalchemy import desc, select

from app.core.db import SessionLocal
from app.models.tables import Project, ProjectStatus

STATUS_HINT = {
    ProjectStatus.PENDING: "项目尚未索引，请在后台点击「重新索引」后再试",
    ProjectStatus.INDEXING: "项目索引进行中，请稍后重试（可在后台查看进度）",
    ProjectStatus.FAILED: "项目最近一次索引失败，请在后台查看索引记录并重新索引",
}


def error(message: str, **extra) -> dict:
    """结构化错误：agent 可读的中文说明 + 可选状态字段。"""
    return {"error": message, **extra}


async def resolve_project(project: str) -> tuple[Project | None, dict | None]:
    """返回 (项目, 错误)。二者必有其一为 None。

    要求项目状态为 ready——非 ready 时图数据可能缺失或半成品（spec: 未就绪返回结构化错误）。
    """
    if not project or not project.strip():
        return None, error("参数 project 不能为空，请传项目名称或项目 id")

    key = project.strip()
    async with SessionLocal() as session:
        found: Project | None = None
        try:
            found = await session.get(Project, uuid.UUID(key))
        except ValueError:
            pass  # 不是 uuid，按名称查
        if found is None:
            found = await session.scalar(
                select(Project)
                .where(Project.name == key)
                .order_by(desc(Project.created_at))  # 重名取最新创建者
                .limit(1)
            )
        if found is None:
            names = list(
                await session.scalars(
                    select(Project.name).order_by(desc(Project.created_at)).limit(10)
                )
            )
        else:
            names = []

    if found is None:
        return None, error(
            f"未找到项目「{key}」",
            available_projects=names,
            hint="project 参数接受项目名称或项目 id，可先调用 list_projects 查看",
        )
    if found.status != ProjectStatus.READY:
        return None, error(
            f"项目「{found.name}」索引未完成（{found.status}）",
            status=found.status,
            resolved_project_id=str(found.id),
            hint=STATUS_HINT.get(found.status, "请在后台重新索引后再试"),
        )
    return found, None
