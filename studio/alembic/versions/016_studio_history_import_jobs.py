"""Phase 12a — Studio history import jobs (Telegram Desktop JSON → Event Mirror).

Revision ID: 016_studio_history_import_jobs
Revises: 015_studio_assistant_rules
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "016_studio_history_import_jobs"
down_revision: Union[str, None] = "015_studio_assistant_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_history_import_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("imported_chat_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_history_import_jobs_status", "studio_history_import_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_studio_history_import_jobs_status", table_name="studio_history_import_jobs")
    op.drop_table("studio_history_import_jobs")
