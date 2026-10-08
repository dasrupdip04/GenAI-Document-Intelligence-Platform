from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.stage2 import DocumentChunk
from app.services.providers import EmbeddingProvider, GeminiProvider


@dataclass
class RetrievedChunk:
    chunk: DocumentChunk
    document: Document
    score: float


class RetrievalService:
    def __init__(self, session: AsyncSession, embedder: EmbeddingProvider | None = None) -> None:
        self.session = session
        self.embedder = embedder or GeminiProvider()

    async def retrieve(self, user_id: str, query: str, top_k: int = 8, document_ids: list[str] | None = None) -> list[RetrievedChunk]:
        if document_ids is not None and not document_ids:
            return []
        vector = (await self.embedder.embed([query]))[0]
        if self.session.bind is not None and self.session.bind.dialect.name == 'sqlite':
            raise RuntimeError('pgvector retrieval requires PostgreSQL.')
        distance = DocumentChunk.embedding.cosine_distance(vector)
        stmt = (select(DocumentChunk, Document, distance.label('distance'))
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.user_id == user_id, Document.status == 'READY', DocumentChunk.embedding.is_not(None)))
        if document_ids is not None:
            stmt = stmt.where(Document.id.in_(document_ids))
        result = await self.session.execute(stmt.order_by(distance).limit(top_k))
        return [RetrievedChunk(chunk, document, 1.0 - float(dist)) for chunk, document, dist in result.all()]
