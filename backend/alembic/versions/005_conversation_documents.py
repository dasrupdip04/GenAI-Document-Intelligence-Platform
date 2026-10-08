"""Associate owned documents with conversations.

Revision ID: 005_conversation_documents
Revises: 004_chunk_vector_index
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005_conversation_documents'
down_revision = '004_chunk_vector_index'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'conversation_documents',
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('document_id', sa.String(),
                  sa.ForeignKey('documents.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_conversation_documents_document_id', 'conversation_documents', ['document_id'])


def downgrade() -> None:
    op.drop_index('ix_conversation_documents_document_id', 'conversation_documents')
    op.drop_table('conversation_documents')
