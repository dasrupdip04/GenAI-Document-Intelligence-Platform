from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str = Field(default='New conversation', min_length=1, max_length=255)
    document_ids: list[str] = Field(default_factory=list)


class ConversationDocumentRead(BaseModel):
    id: str
    filename: str
    file_type: str
    status: str
    error_message: str | None = None


class ConversationDocumentAttach(BaseModel):
    document_id: str = Field(min_length=1)


class CitationRead(BaseModel):
    id: UUID
    chunk_id: UUID
    document_id: str
    filename: str
    page_number: int | None = None
    relevance_score: float


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: str
    content: str
    created_at: datetime | None = None
    citations: list[CitationRead] = Field(default_factory=list)


class ConversationRead(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageRead] = Field(default_factory=list)
    documents: list[ConversationDocumentRead] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class QuestionCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    document_ids: list[str] | None = None


class AnswerRead(MessageRead):
    pass
