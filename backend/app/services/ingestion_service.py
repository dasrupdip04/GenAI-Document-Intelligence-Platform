from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.stage2 import DocumentChunk, IngestionJob
from app.services.extraction import DocumentExtractor, RecursiveChunker
from app.services.providers import EmbeddingProvider, GeminiProvider

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, session: AsyncSession, embedder: EmbeddingProvider | None = None,
                 extractor: DocumentExtractor | None = None, chunker: RecursiveChunker | None = None) -> None:
        self.session = session
        self.embedder = embedder or GeminiProvider()
        self.extractor = extractor or DocumentExtractor()
        self.chunker = chunker or RecursiveChunker()

    async def ingest(self, document_id: str, job_id: UUID) -> None:
        started = monotonic()
        job = await self.session.get(IngestionJob, job_id)
        document = await self.session.get(Document, document_id)
        if not job or not document:
            return
        job.status = 'PROCESSING'
        job.started_at = datetime.now(timezone.utc)
        document.status = 'PROCESSING'
        await self.session.commit()
        try:
            pages = self.extractor.extract(document.storage_path, document.file_type)
            rows: list[tuple[str, int | None]] = []
            for page in pages:
                rows.extend((chunk, page.page_number) for chunk in self.chunker.split(page.text))
            if not rows:
                raise ValueError('No readable text found in the document.')
            vectors = await self.embedder.embed([row[0] for row in rows])
            if len(vectors) != len(rows):
                raise RuntimeError('Embedding provider returned an unexpected result count.')
            await self.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            for index, ((content, page_number), embedding) in enumerate(zip(rows, vectors)):
                self.session.add(DocumentChunk(document_id=document_id, chunk_index=index, content=content,
                    page_number=page_number, character_count=len(content), embedding=embedding,
                    chunk_metadata={'filename': document.filename, 'page_number': page_number, 'chunk_index': index}))
            job.status = 'READY'
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = None
            document.status = 'READY'
            document.error_message = None
            await self.session.commit()
            logger.info('ingestion completed document_id=%s job_id=%s status=READY chunks=%d duration_ms=%.1f',
                        document_id, job_id, len(rows), (monotonic() - started) * 1000)
        except Exception as exc:
            await self.session.rollback()
            logger.exception('ingestion failed document_id=%s job_id=%s duration_ms=%.1f',
                             document_id, job_id, (monotonic() - started) * 1000)
            job = await self.session.get(IngestionJob, job_id)
            document = await self.session.get(Document, document_id)
            if job:
                job.status = 'FAILED'; job.error_message = str(exc)[:1000]; job.completed_at = datetime.now(timezone.utc)
            if document:
                document.status = 'FAILED'; document.error_message = 'Document ingestion failed.'
            await self.session.commit()
