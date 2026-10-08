"""Stage 2 ingestion, pgvector chunks, conversations and citations.

Revision ID: 003_stage2_rag
Revises: 002_initial_schema
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = '003_stage2_rag'
down_revision = '002_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('error_message', sa.String(1000), nullable=True))
    op.create_table('document_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', sa.String(), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False), sa.Column('content', sa.Text(), nullable=False),
        sa.Column('page_number', sa.Integer()), sa.Column('character_count', sa.Integer(), nullable=False),
        sa.Column('embedding', Vector(768)), sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_document_chunks_document_id', 'document_chunks', ['document_id'])
    op.create_index('ix_document_chunks_document_index', 'document_chunks', ['document_id', 'chunk_index'])
    op.create_table('conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])
    op.create_table('messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False), sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])
    op.create_table('citations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_chunks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_number', sa.Integer()), sa.Column('relevance_score', sa.Float(), nullable=False))
    op.create_index('ix_citations_message_id', 'citations', ['message_id'])
    op.create_index('ix_citations_document_id', 'citations', ['document_id'])
    op.create_table('ingestion_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', sa.String(), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('error_message', sa.String(1000)),
        sa.Column('started_at', sa.DateTime(timezone=True)), sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_ingestion_jobs_document_id', 'ingestion_jobs', ['document_id'])
    op.create_index('ix_ingestion_jobs_status', 'ingestion_jobs', ['status'])


def downgrade() -> None:
    op.drop_table('ingestion_jobs'); op.drop_table('citations'); op.drop_index('ix_messages_conversation_id', 'messages'); op.drop_table('messages')
    op.drop_index('ix_conversations_user_id', 'conversations'); op.drop_table('conversations')
    op.drop_index('ix_document_chunks_document_index', 'document_chunks'); op.drop_index('ix_document_chunks_document_id', 'document_chunks')
    op.drop_table('document_chunks'); op.drop_column('documents', 'error_message')
