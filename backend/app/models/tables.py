import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProjectStatus:
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class JobStatus:
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStage:
    CLONE = "clone"
    PARSE = "parse"
    SUMMARIZE = "summarize"
    EMBED = "embed"
    GRAPH = "graph"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    git_url: Mapped[str] = mapped_column(String(500))
    git_token_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    default_branch: Mapped[str | None] = mapped_column(String(100), default=None)
    status: Mapped[str] = mapped_column(String(20), default=ProjectStatus.PENDING)
    last_indexed_commit: Mapped[str | None] = mapped_column(String(40), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    jobs: Mapped[list["IndexJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class IndexJob(Base):
    __tablename__ = "index_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(20), default="full")
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.RUNNING)
    stage: Mapped[str] = mapped_column(String(20), default=JobStage.CLONE)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_text: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    project: Mapped[Project] = relationship(back_populates="jobs")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
