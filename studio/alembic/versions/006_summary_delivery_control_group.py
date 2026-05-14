"""Phase 6d — summary delivery to Telegram control group.

Revision ID: 006_summary_delivery_control_group
Revises: 005_chat_summaries
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "006_summary_delivery_control_group"
down_revision: Union[str, None] = "005_chat_summaries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studio_chat_summaries",
        sa.Column(
            "delivery_status",
            sa.String(length=64),
            server_default="not_requested",
            nullable=False,
        ),
    )
    op.add_column(
        "studio_chat_summaries",
        sa.Column("delivery_retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("studio_chat_summaries", sa.Column("delivery_last_error", sa.Text(), nullable=True))
    op.add_column("studio_chat_summaries", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "studio_chat_summaries",
        sa.Column("destination_control_group_id", pg.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("studio_chat_summaries", sa.Column("telegram_message_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_studio_chat_summaries_destination_control_group",
        "studio_chat_summaries",
        "studio_control_groups",
        ["destination_control_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_studio_chat_summaries_delivery_status",
        "studio_chat_summaries",
        ["delivery_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_studio_chat_summaries_delivery_status", table_name="studio_chat_summaries")
    op.drop_constraint(
        "fk_studio_chat_summaries_destination_control_group",
        "studio_chat_summaries",
        type_="foreignkey",
    )
    op.drop_column("studio_chat_summaries", "telegram_message_id")
    op.drop_column("studio_chat_summaries", "destination_control_group_id")
    op.drop_column("studio_chat_summaries", "delivered_at")
    op.drop_column("studio_chat_summaries", "delivery_last_error")
    op.drop_column("studio_chat_summaries", "delivery_retry_count")
    op.drop_column("studio_chat_summaries", "delivery_status")
