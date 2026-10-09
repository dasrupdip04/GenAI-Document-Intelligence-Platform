"""Recompute stored document chunk vectors using the configured local embedder."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.database import AsyncSessionLocal, engine
from app.models.stage2 import DocumentChunk
from app.services.providers import LocalEmbeddingProvider

BATCH_SIZE = 32


async def reindex() -> None:
    embedder = LocalEmbeddingProvider()
    async with AsyncSessionLocal() as session:
        chunks = list((await session.scalars(
            select(DocumentChunk).order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        )).all())
        for offset in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[offset:offset + BATCH_SIZE]
            vectors = await embedder.embed([chunk.content for chunk in batch])
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
            await session.commit()
            print(f"Re-embedded {min(offset + len(batch), len(chunks))}/{len(chunks)} chunks")


async def main() -> None:
    try:
        await reindex()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
