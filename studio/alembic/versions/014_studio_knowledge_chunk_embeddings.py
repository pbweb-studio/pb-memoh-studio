"""Phase 10c — Studio KB chunk embeddings (pgvector) + status fields.

Revision ID: 014_studio_knowledge_chunk_embeddings
Revises: 013_studio_knowledge_base
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_studio_knowledge_chunk_embeddings"
down_revision: Union[str, None] = "013_studio_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Должно совпадать с KNOWLEDGE_EMBEDDING_VECTOR_DIM и дефолтом STUDIO_KB_EMBEDDING_DIM.
_EMBEDDING_DIM = 384


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.add_column("studio_knowledge_chunks", sa.Column("embedding_model", sa.String(length=128), nullable=True))
    op.add_column("studio_knowledge_chunks", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "studio_knowledge_chunks",
        sa.Column("embedding_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column("studio_knowledge_chunks", sa.Column("embedding_last_error", sa.Text(), nullable=True))

    if is_pg:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        from pgvector.sqlalchemy import Vector

        op.add_column("studio_knowledge_chunks", sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=True))
    else:
        op.add_column("studio_knowledge_chunks", sa.Column("embedding", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("studio_knowledge_chunks", "embedding")
    op.drop_column("studio_knowledge_chunks", "embedding_last_error")
    op.drop_column("studio_knowledge_chunks", "embedding_status")
    op.drop_column("studio_knowledge_chunks", "embedded_at")
    op.drop_column("studio_knowledge_chunks", "embedding_model")
