"""Pydantic 请求/响应模型 — 与 docs/api.md 契约一致。"""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ============================================================
# 通用
# ============================================================
class PageQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


# ============================================================
# 认证
# ============================================================
class LoginReq(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class RegisterReq(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    display_name: Optional[str] = Field(None, max_length=50)


class RefreshReq(BaseModel):
    refresh_token: str


class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


# ============================================================
# 用户
# ============================================================
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    username: str
    email: str
    role: str
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreateReq(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field("user", pattern="^(admin|user)$")
    display_name: Optional[str] = Field(None, max_length=50)


class UserUpdateReq(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[str] = Field(None, pattern="^(admin|user)$")
    display_name: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=6, max_length=128)


# ============================================================
# 知识库
# ============================================================
class KbCreateReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = ""
    chunk_size: int = Field(500, ge=100, le=2000)
    chunk_overlap: int = Field(50, ge=0, le=500)
    embedding_dim: int = Field(3584, ge=1)
    embedding_model: str = Field("gte-qwen2", max_length=100)
    member_user_ids: list[UUID] = Field(default_factory=list)
    member_roles: dict[str, str] = Field(default_factory=dict)  # user_id -> role


class KbUpdateReq(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    chunk_size: Optional[int] = Field(None, ge=100, le=2000)
    chunk_overlap: Optional[int] = Field(None, ge=0, le=500)
    status: Optional[str] = Field(None, pattern="^(active|archived)$")


class KbOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID
    name: str
    description: str
    status: str
    chunk_size: int
    chunk_overlap: int
    embedding_dim: int
    embedding_model: str
    settings: dict
    created_at: datetime
    updated_at: datetime


class KbDetailOut(KbOut):
    document_count: int = 0
    chunk_count: int = 0
    members: list["KbMemberOut"] = []


class KbMemberReq(BaseModel):
    user_id: UUID
    role: str = Field("viewer", pattern="^(owner|editor|viewer)$")


class KbMemberUpdateReq(BaseModel):
    role: str = Field(..., pattern="^(owner|editor|viewer)$")


class KbMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kb_id: UUID
    user_id: UUID
    role: str
    created_at: datetime
    # 可选：join user 信息
    username: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None


# ============================================================
# 文档
# ============================================================
class DocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kb_id: UUID
    uploaded_by: UUID
    filename: str
    file_type: str
    file_size: int
    minio_key: str
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    version: int
    meta: dict = {}
    uploaded_at: datetime
    indexed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class DocUploadOut(BaseModel):
    document_id: UUID
    status: str
    task_id: UUID


class ProcessTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    task_type: str
    status: str
    celery_task_id: Optional[str] = None
    result: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime


class DocDetailOut(BaseModel):
    document: DocOut
    task: Optional[ProcessTaskOut] = None


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    kb_id: UUID
    chunk_index: int
    content: str
    token_count: int
    metadata: dict
    created_at: datetime


# ============================================================
# 检索
# ============================================================
class SearchReq(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field("hybrid", pattern="^(hybrid|vector|keyword)$")
    top_k: int = Field(10, ge=1, le=100)
    filters: Optional[dict] = None


class SearchResultItem(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    chunk_index: int
    content: str
    score: float
    match_type: str  # vector | keyword | hybrid
    metadata: dict = {}


class SearchOut(BaseModel):
    items: list[SearchResultItem]
    total: int
    took_ms: int


# ============================================================
# RAG 问答
# ============================================================
class ChatMessageReq(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatReq(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[UUID] = None
    history: list[ChatMessageReq] = Field(default_factory=list)
    top_n: int = Field(5, ge=1, le=20)
    system_prompt: Optional[str] = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kb_id: UUID
    user_id: UUID
    title: str
    system_prompt: Optional[dict] = None
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    sources: Optional[list] = None
    token_count: int
    created_at: datetime


class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]


# ============================================================
# 监控
# ============================================================
class HealthOut(BaseModel):
    status: str
    services: dict
    version: str


class MonitorOut(BaseModel):
    document_stats: dict
    chunk_count: int
    es_index: dict
    minio: dict
    celery: dict
    kb_count: int
    user_count: int
