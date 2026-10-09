"""Clear old vectors and change pgvector storage to MiniLM's 384 dimensions.

Revision ID: 006_minilm_vectors_384
Revises: 005_conversation_documents
"""
from alembic import op

revision = '006_minilm_vectors_384'
down_revision = '005_conversation_documents'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('ix_document_chunks_embedding_hnsw', 'document_chunks')
    # Preserve chunk text and metadata; discard incompatible 768d vectors.
    op.execute('ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(384) USING NULL::vector(384)')
    op.create_index('ix_document_chunks_embedding_hnsw', 'document_chunks', ['embedding'],
                    postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})


def downgrade() -> None:
    op.drop_index('ix_document_chunks_embedding_hnsw', 'document_chunks')
    op.execute('ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(768) USING NULL::vector(768)')
    op.create_index('ix_document_chunks_embedding_hnsw', 'document_chunks', ['embedding'],
                    postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
