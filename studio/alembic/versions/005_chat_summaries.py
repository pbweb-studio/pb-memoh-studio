"""Phase 6a — studio_chat_summaries (planner infrastructure, no LLM).

Revision ID: 005_chat_summaries
Revises: 004_system_notification_delivery
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "005_chat_summaries"
down_revision: Union[str, None] = "004_system_notification_delivery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_chat_summaries",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_role", sa.String(length=32), nullable=False),
        sa.Column("summary_type", sa.String(length=32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_event_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["studio_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chat_id",
            "summary_type",
            "period_start",
            "period_end",
            name="uq_studio_chat_summaries_chat_type_period",
        ),
    )
    op.create_index("ix_studio_chat_summaries_chat_status", "studio_chat_summaries", ["chat_id", "status"])
    op.create_index("ix_studio_chat_summaries_created", "studio_chat_summaries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_studio_chat_summaries_created", table_name="studio_chat_summaries")
    op.drop_index("ix_studio_chat_summaries_chat_status", table_name="studio_chat_summaries")
    op.drop_table("studio_chat_summaries")
