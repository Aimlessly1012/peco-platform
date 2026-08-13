"""API 请求/响应模型。注意：任何响应模型都不含 token 字段（spec: 不回显 token）。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    git_url: str = Field(min_length=8, max_length=500)
    git_token: str | None = None
    default_branch: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    git_url: str
    default_branch: str | None
    status: str
    index_depth: str = "deep"
    last_indexed_commit: str | None
    created_at: datetime
    updated_at: datetime


class IndexJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    status: str
    stage: str
    progress: int
    stats_json: dict
    error_text: str | None
    started_at: datetime
    finished_at: datetime | None


class SequenceOut(BaseModel):
    """单张模块时序图；mermaid 为空表示两次校验均失败，前端显示 fallback_text。"""

    module_key: str
    module_name: str
    kind: str = ""
    route_prefix: str = ""
    mermaid: str = ""
    fallback_text: str = ""


class BusinessFlowOut(BaseModel):
    """业务流程图（M6）。mermaid 为空表示降级，前端显示 fallback_text。"""

    title: str
    mermaid: str = ""
    fallback_text: str = ""


class ReportOut(BaseModel):
    """理解报告（M6）。feature_map_markdown / dataflow_mermaid 为空表示旧报告，
    前端分别回退渲染结构导图、隐藏数据流卡片。"""

    project_id: uuid.UUID
    doc_markdown: str
    feature_map_markdown: str = ""  # 需求功能思维导图（markmap 渲染）
    business_flows: list[BusinessFlowOut] = []  # 业务流程图（需求方向）
    page_map_markdown: str = ""     # 页面结构导图（markmap 渲染）
    mindmap_mermaid: str = ""       # 模块结构导图（功能地图页签）
    dataflow_mermaid: str = ""
    sequences: list[SequenceOut]
    depth: str = "deep"  # fast 报告只有程序化两件，前端据此显示升级引导
    generated_at: datetime


class ModuleFileOut(BaseModel):
    path: str
    language: str = ""
    summary: str = ""  # L2 文件摘要


class ModuleOut(BaseModel):
    key: str
    name: str
    kind: str
    route_prefix: str = ""
    summary: str = ""  # L3 模块摘要
    files: list[ModuleFileOut]


class ModuleMapOut(BaseModel):
    """功能地图：实时读 Neo4j 的模块→文件树。"""

    project_id: uuid.UUID
    project_name: str
    project_summary: str  # L4 项目总览
    modules: list[ModuleOut]


class ChatSessionCreate(BaseModel):
    title: str | None = None


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    created_at: datetime


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    citations_json: list
    created_at: datetime


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
