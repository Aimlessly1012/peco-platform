"""聊天 API：会话管理 + SSE 流式问答 + 引用持久化。"""
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.db import SessionLocal, get_session
from app.models.tables import ChatMessage, ChatSession, Project, ProjectStatus
from app.schemas import AskRequest, ChatMessageOut, ChatSessionCreate, ChatSessionOut
from app.services.qa.workflow import qa_graph

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post(
    "/projects/{project_id}/sessions", response_model=ChatSessionOut, status_code=201
)
async def create_session(
    project_id: uuid.UUID,
    payload: ChatSessionCreate,
    session: AsyncSession = Depends(get_session),
):
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "项目不存在")
    chat = ChatSession(project_id=project_id, title=payload.title or "新会话")
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return chat


@router.get("/projects/{project_id}/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    result = await session.scalars(
        select(ChatSession)
        .where(ChatSession.project_id == project_id)
        .order_by(desc(ChatSession.created_at))
    )
    return list(result)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(
    session_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    result = await session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return list(result)


@router.post("/sessions/{session_id}/ask")
async def ask(session_id: uuid.UUID, payload: AskRequest):
    """SSE 流式问答。事件：token / citations / done / error。"""
    async with SessionLocal() as db:
        chat = await db.get(ChatSession, session_id)
        if chat is None:
            raise HTTPException(404, "会话不存在")
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

    return EventSourceResponse(event_stream())
