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
    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.embedder = embedder or GeminiProvider()

    async def retrieve_many(
        self,
        user_id: str,
        queries: list[str],
        top_k: int = 8,
        document_ids: list[str] | None = None,
    ) -> list[list[RetrievedChunk]]:
        """
        Retrieve results for multiple queries while batching all
        query embeddings into ONE embedding-provider request.

        This preserves the existing multi-query + step-back +
        RRF architecture but avoids one Gemini embedding HTTP
        request per retrieval query.
        """

        if not queries:
            return []

        # Remove duplicate queries while preserving order.
        unique_queries = list(dict.fromkeys(
            query.strip()
            for query in queries
            if query and query.strip()
        ))

        if not unique_queries:
            return []

        if document_ids is not None and not document_ids:
            return [[] for _ in unique_queries]

        # IMPORTANT:
        # One Gemini embedding API call for all retrieval queries.
        vectors = await self.embedder.embed(unique_queries)

        if len(vectors) != len(unique_queries):
            raise RuntimeError(
                "Embedding provider returned an unexpected "
                "number of vectors."
            )

        results_by_query: dict[str, list[RetrievedChunk]] = {}

        for query, vector in zip(unique_queries, vectors):
            results_by_query[query] = await self._retrieve_vector(
                user_id=user_id,
                vector=vector,
                top_k=top_k,
                document_ids=document_ids,
            )

        return [
            results_by_query.get(query, [])
            for query in unique_queries
        ]

    async def _retrieve_vector(
        self,
        user_id: str,
        vector: list[float],
        top_k: int,
        document_ids: list[str] | None,
    ) -> list[RetrievedChunk]:
        if (
            self.session.bind is not None
            and self.session.bind.dialect.name == "sqlite"
        ):
            raise RuntimeError(
                "pgvector retrieval requires PostgreSQL."
            )

        distance = DocumentChunk.embedding.cosine_distance(
            vector
        )

        stmt = (
            select(
                DocumentChunk,
                Document,
                distance.label("distance"),
            )
            .join(
                Document,
                Document.id == DocumentChunk.document_id,
            )
            .where(
                Document.user_id == user_id,
                Document.status == "READY",
                DocumentChunk.embedding.is_not(None),
            )
        )

        if document_ids is not None:
            stmt = stmt.where(
                Document.id.in_(document_ids)
            )

        result = await self.session.execute(
            stmt
            .order_by(distance)
            .limit(top_k)
        )

        return [
            RetrievedChunk(
                chunk=chunk,
                document=document,
                score=1.0 - float(distance_value),
            )
            for chunk, document, distance_value
            in result.all()
        ]

    async def retrieve(
        self,
        user_id: str,
        query: str,
        top_k: int = 8,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """
        Backwards-compatible single-query retrieval method.
        """

        results = await self.retrieve_many(
            user_id=user_id,
            queries=[query],
            top_k=top_k,
            document_ids=document_ids,
        )

        return results[0] if results else []
