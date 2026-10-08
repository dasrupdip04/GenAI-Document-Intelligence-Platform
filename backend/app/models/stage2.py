from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.database import Base


class PortableVector(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = dimensions
        super().__init__()

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(Vector(self.dimensions) if dialect.name == 'postgresql' else JSON())


class DocumentChunk(Base):
    __tablename__ = 'document_chunks'
    __table_args__ = (Index('ix_document_chunks_document_index', 'document_id', 'chunk_index'),)

    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(PortableVector(get_settings().embedding_dimensions))
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column('metadata', JSON().with_variant(JSONB(), 'postgresql'), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Conversation(Base):
    __tablename__ = 'conversations'
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default='New conversation')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[object] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Citation(Base):
    __tablename__ = 'citations'
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[object] = mapped_column(ForeignKey('messages.id', ondelete='CASCADE'), nullable=False, index=True)
    chunk_id: Mapped[object] = mapped_column(ForeignKey('document_chunks.id', ondelete='CASCADE'), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'), nullable=False, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)


class IngestionJob(Base):
    __tablename__ = 'ingestion_jobs'
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='PENDING', index=True)
    error_message: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
