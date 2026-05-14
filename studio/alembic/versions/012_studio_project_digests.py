"""Phase 9b — project digests (aggregated chat summaries).

Revision ID: 012_studio_project_digests
Revises: 011_studio_projects
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "012_studio_project_digests"
down_revision: Union[str, None] = "011_studio_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_project_digests",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("digest_type", sa.String(length=32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("source_chat_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_summary_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("digest_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "delivery_status",
            sa.String(length=64),
            nullable=False,
            server_default="not_requested",
        ),
        sa.Column("delivery_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivery_last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["studio_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "digest_type",
            "period_start",
            "period_end",
            name="uq_studio_project_digests_project_type_period",
        ),
    )
    op.create_index(
        "ix_studio_project_digests_project_created",
        "studio_project_digests",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_studio_project_digests_delivery_status",
        "studio_project_digests",
        ["delivery_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_studio_project_digests_delivery_status", table_name="studio_project_digests")
    op.drop_index("ix_studio_project_digests_project_created", table_name="studio_project_digests")
    op.drop_table("studio_project_digests")
