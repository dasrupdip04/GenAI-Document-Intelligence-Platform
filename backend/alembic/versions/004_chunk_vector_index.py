"""Add cosine HNSW index for pgvector retrieval.

Revision ID: 004_chunk_vector_index
Revises: 003_stage2_rag
"""
from alembic import op

revision = '004_chunk_vector_index'
down_revision = '003_stage2_rag'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_document_chunks_embedding_hnsw', 'document_chunks', ['embedding'],
                    postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})


def downgrade() -> None:
    op.drop_index('ix_document_chunks_embedding_hnsw', 'document_chunks')
