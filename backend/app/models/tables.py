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
    """六阶段（M3 新增 report）。进度区间：clone 0-10, parse 10-25, summarize 25-55,
    embed 55-85, graph 85-92, report 92-100。"""

    CLONE = "clone"
    PARSE = "parse"
    SUMMARIZE = "summarize"
    EMBED = "embed"
    GRAPH = "graph"
    REPORT = "report"


class IndexDepth:
    """索引深度（M5 D7）。fast = 零 LLM 录入，deep = 完整理解。"""

    DEEP = "deep"
    FAST = "fast"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    git_url: Mapped[str] = mapped_column(String(500))
    git_token_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    default_branch: Mapped[str | None] = mapped_column(String(100), default=None)
    status: Mapped[str] = mapped_column(String(20), default=ProjectStatus.PENDING)
    index_depth: Mapped[str] = mapped_column(String(10), default=IndexDepth.DEEP)
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
    report: Mapped["UnderstandingReport | None"] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
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


class UnderstandingReport(Base):
    """项目理解报告：一项目一行（project_id unique），重索引覆盖写（设计 D3）。

    sequences_json: [{module_key, module_name, mermaid, fallback_text}]
    """

    __tablename__ = "understanding_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    doc_markdown: Mapped[str] = mapped_column(Text, default="")
    # M6：需求功能思维导图（markdown 层级文本，markmap 直接渲染）。旧报告为 NULL
    feature_map_markdown: Mapped[str | None] = mapped_column(Text, default=None)
    # M5：模块结构导图（Project→Module），M6 起归功能地图页签使用
    mindmap_mermaid: Mapped[str] = mapped_column(Text, default="")
    # M5：模块数据流图。旧报告为 NULL，前端据此隐藏卡片
    dataflow_mermaid: Mapped[str | None] = mapped_column(Text, default=None)
    # M6：业务流程图 [{title, mermaid, fallback_text}]。fast 与旧报告为 NULL
    business_flows_json: Mapped[list | None] = mapped_column(JSON, default=None)
    sequences_json: Mapped[list] = mapped_column(JSON, default=list)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    project: Mapped[Project] = relationship(back_populates="report")


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
