"""聊天 API：会话管理 + SSE 流式问答 + 引用持久化。"""
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.db import SessionLocal, get_session
from app.models.tables import (
    ChatMessage,
    ChatSession,
    Project,
    ProjectStatus,
    User,
    UserRole,
)
from app.schemas import AskRequest, ChatMessageOut, ChatSessionCreate, ChatSessionOut
from app.services.auth.deps import require_user
from app.services.qa.workflow import qa_graph

logger = logging.getLogger(__name__)

# M9 B3：LangGraph 节点名 → 前端可消费的阶段标识。
# 只映射这几个已知节点，其余（图内部的 __start__ / RunnableSequence 等）忽略；
# 前端对未知 stage 也应忽略，双向向前兼容
STAGE_NODES = {
    "understand": "understand",   # M9 合并前是 rewrite + classify 两个节点
    "retrieve": "retrieve",
    "generate": "generate",
}
# M8：聊天全组要求登录态；会话按人隔离见 _owned_session
router = APIRouter(tags=["chat"], dependencies=[Depends(require_user)])


def _visible_to(user: User):
    """会话可见性条件（M8 B7）：自己的会话；admin 另可见 user_id 为空的历史会话。"""
    if user.role == UserRole.ADMIN:
        return or_(ChatSession.user_id == user.id, ChatSession.user_id.is_(None))
    return ChatSession.user_id == user.id


async def _owned_session(
    session_id: uuid.UUID, session: AsyncSession, user: User
) -> ChatSession:
    """取自己的会话。别人的会话一律 404——403 会泄露"这个会话存在"。"""
    chat = await session.scalar(
        select(ChatSession).where(ChatSession.id == session_id, _visible_to(user))
    )
    if chat is None:
        raise HTTPException(404, "会话不存在")
    return chat


@router.post(
    "/projects/{project_id}/sessions", response_model=ChatSessionOut, status_code=201
)
async def create_session(
    project_id: uuid.UUID,
    payload: ChatSessionCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "项目不存在")
    chat = ChatSession(
        project_id=project_id, title=payload.title or "新会话", user_id=user.id
    )
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return chat


@router.get("/projects/{project_id}/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    result = await session.scalars(
        select(ChatSession)
        .where(ChatSession.project_id == project_id, _visible_to(user))
        .order_by(desc(ChatSession.created_at))
    )
    return list(result)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    await _owned_session(session_id, session, user)
    result = await session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return list(result)


@router.post("/sessions/{session_id}/ask")
async def ask(
    session_id: uuid.UUID,
    payload: AskRequest,
    user: User = Depends(require_user),
):
    """SSE 流式问答。事件：token / citations / done / error。"""
    async with SessionLocal() as db:
        # 归属校验走这条自建连接（本端点不用注入的 session）——
        # 漏了这句，别人的会话 ID 就能被拿来提问并把消息写进去
        chat = await _owned_session(session_id, db, user)
        project = await db.get(Project, chat.project_id)
        if project.status != ProjectStatus.READY:
            # spec: 项目就绪校验——不产生模型调用
            raise HTTPException(
                409, f"项目索引未完成（当前状态：{project.status}），暂不能提问"
            )
        history_rows = await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(desc(ChatMessage.created_at))
            .limit(6)
        )
        history = [
            {"role": m.role, "content": m.content}
            for m in reversed(list(history_rows))
        ]
        user_msg = ChatMessage(
            session_id=session_id, role="user", content=payload.question
        )
        db.add(user_msg)
        await db.commit()
        project_id = str(chat.project_id)

    async def event_stream():
        answer_parts: list[str] = []
        citations: list[dict] = []
        sent_stages: set[str] = set()
        try:
            async for event in qa_graph.astream_events(
                {
                    "project_id": project_id,
                    "question": payload.question,
                    "history": history,
                },
                version="v2",
            ):
                kind = event["event"]
                if kind == "on_chain_start":
                    stage = STAGE_NODES.get(event.get("name") or "")
                    if stage and stage not in sent_stages:
                        sent_stages.add(stage)   # 每阶段只报一次
                        yield {"event": "stage", "data": json.dumps({"stage": stage})}
                    continue
                if kind == "on_chat_model_stream":
                    # 只转发 generate 节点（tags=answer）的流，rewrite/classify 不进答案
                    if "answer" not in (event.get("tags") or []):
                        continue
                    token = event["data"]["chunk"].content
                    if token:
                        answer_parts.append(token)
                        yield {"event": "token", "data": json.dumps({"t": token})}
                elif kind == "on_chain_end" and event.get("name") == "retrieve":
                    items = event["data"]["output"].get("items") or []
                    # 必须与提示词里的「资料 N」编号同序同长：答案中的 [n] 上标按下标定位，
                    # 过滤掉关联带出项会让编号整体错位（关联项由 via_edge 字段区分展示）
                    citations = [c.citation() for c in items]
            yield {"event": "citations", "data": json.dumps(citations)}

            answer = "".join(answer_parts)
            async with SessionLocal() as db:
                db.add(
                    ChatMessage(
                        session_id=session_id,
                        role="assistant",
                        content=answer,
                        citations_json=citations,
                    )
                )
                await db.commit()
            yield {"event": "done", "data": "{}"}
        except Exception as e:  # noqa: BLE001 — SSE 内错误必须转事件，用户消息已保留
            logger.exception("问答失败")
            yield {
                "event": "error",
                "data": json.dumps({"message": f"生成失败：{type(e).__name__}，请重试"}),
            }

    # sep 显式锁定 \n：sse-starlette 新版默认 \r\n，曾使前端按 \n\n 分块的解析
    # 整场流零事件（前端已同时兼容两种分隔，双保险）
    return EventSourceResponse(event_stream(), sep="\n")
