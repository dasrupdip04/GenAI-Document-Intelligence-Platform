"""Enable pgvector extension

Revision ID: 001_enable_pgvector
Revises: 
Create Date: 2026-10-08 18:50:00.000000

"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = '001_enable_pgvector'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')


def downgrade() -> None:
    op.execute('DROP EXTENSION IF EXISTS vector')
