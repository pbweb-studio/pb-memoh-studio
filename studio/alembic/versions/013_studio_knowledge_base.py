"""Phase 10a — Studio knowledge base (documents, versions, chunks; no embeddings).

Revision ID: 013_studio_knowledge_base
Revises: 012_studio_project_digests
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "013_studio_knowledge_base"
down_revision: Union[str, None] = "012_studio_project_digests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_knowledge_documents",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["studio_projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_knowledge_documents_project_id", "studio_knowledge_documents", ["project_id"])
    op.create_index("ix_studio_knowledge_documents_status", "studio_knowledge_documents", ["status"])

    op.create_table(
        "studio_knowledge_document_versions",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_name", sa.String(length=128), nullable=True),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["studio_knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_studio_kb_doc_versions_doc_ver"),
        sa.UniqueConstraint("document_id", "content_hash", name="uq_studio_kb_doc_versions_doc_hash"),
    )
    op.create_index(
        "ix_studio_knowledge_document_versions_document_id",
        "studio_knowledge_document_versions",
        ["document_id"],
    )

    op.create_table(
        "studio_knowledge_chunks",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["studio_knowledge_document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id", "chunk_index", name="uq_studio_kb_chunks_ver_idx"),
    )
    op.create_index(
        "ix_studio_knowledge_chunks_document_version_id",
        "studio_knowledge_chunks",
        ["document_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_studio_knowledge_chunks_document_version_id", table_name="studio_knowledge_chunks")
    op.drop_table("studio_knowledge_chunks")
    op.drop_index("ix_studio_knowledge_document_versions_document_id", table_name="studio_knowledge_document_versions")
    op.drop_table("studio_knowledge_document_versions")
    op.drop_index("ix_studio_knowledge_documents_status", table_name="studio_knowledge_documents")
    op.drop_index("ix_studio_knowledge_documents_project_id", table_name="studio_knowledge_documents")
    op.drop_table("studio_knowledge_documents")
