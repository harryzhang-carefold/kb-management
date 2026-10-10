"""SQLAlchemy ORM 模型 — 与 infra/init_db.sql 表结构一致。"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    display_name: Mapped[str] = mapped_column(String(50), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('admin','user')", name="ck_user_role"),
    )

    def __repr__(self):
        return f"<User {self.username} role={self.role}>"


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, default=3584, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), default="gte-qwen2", nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_kb_status"),
        Index("idx_kb_owner", "owner_id"),
        Index("idx_kb_status_active", "status",
              postgresql_where="NOT is_deleted"),
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="kb", cascade="all, delete-orphan", lazy="dynamic")
    members: Mapped[list["KbMember"]] = relationship(
        back_populates="kb", cascade="all, delete-orphan", lazy="dynamic")
    owner: Mapped["User"] = relationship(back_populates="owned_kbs")


class KbMember(Base):
    __tablename__ = "kb_member"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('owner','editor','viewer')", name="ck_kbmember_role"),
        Index("uk_kb_member", "kb_id", "user_id", unique=True),
        Index("idx_kb_member_user", "user_id"),
    )

    kb: Mapped["KnowledgeBase"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()


class Document(Base):
    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    minio_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="uploaded", nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    full_text: Mapped[Optional[str]] = mapped_column(Text, default=None)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','parsing','parsed','chunking','embedding','indexed','failed')",
            name="ck_doc_status"),
        CheckConstraint(
            "file_type IN ('pdf','docx','pptx','xlsx','txt','md','html','jpg','png','bmp','webp','tiff')",
            name="ck_doc_filetype"),
        Index("idx_doc_kb", "kb_id", postgresql_where="NOT is_deleted"),
        Index("idx_doc_status", "status", postgresql_where="NOT is_deleted"),
    )

    kb: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="doc")
    tasks: Mapped[list["ProcessTask"]] = relationship(back_populates="doc")


class Chunk(Base):
    __tablename__ = "chunk"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_chunk_doc", "document_id"),
        Index("idx_chunk_kb", "kb_id"),
    )

    doc: Mapped["Document"] = relationship(back_populates="chunks")


class ProcessTask(Base):
    __tablename__ = "process_task"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    result: Mapped[Optional[str]] = mapped_column(Text, default=None)
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "task_type IN ('parse','chunk_index','pageindex','cleanup')",
            name="process_task_task_type_check"),
        CheckConstraint("status IN ('pending','running','success','failed')", name="ck_task_status"),
        Index("idx_task_doc", "document_id"),
        Index("idx_task_status", "status"),
    )

    doc: Mapped["Document"] = relationship(back_populates="tasks")


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    system_prompt: Mapped[Optional[dict]] = mapped_column(JSONB, default=None)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_conv_kb", "kb_id"),
        Index("idx_conv_user", "user_id"),
        Index("idx_conv_created", "created_at"),
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conv", cascade="all, delete-orphan", lazy="dynamic",
        order_by="Message.created_at")


class Message(Base):
    __tablename__ = "message"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[Optional[list]] = mapped_column(JSONB, default=None)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_msg_role"),
        Index("idx_msg_conv", "conversation_id"),
        Index("idx_msg_created", "created_at"),
    )

    conv: Mapped["Conversation"] = relationship(back_populates="messages")


# 给 User 补一个反向关系（避免循环导入问题）
User.owned_kbs = relationship(
    "KnowledgeBase",
    primaryjoin="User.id == KnowledgeBase.owner_id",
    back_populates="owner",
    lazy="dynamic",
)
