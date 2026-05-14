"""Phase 7a — control group summary commands via Event Mirror.

Revision ID: 007_studio_control_commands
Revises: 006_summary_delivery_control_group
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "007_studio_control_commands"
down_revision: Union[str, None] = "006_summary_delivery_control_group"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_control_commands",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_update_id", sa.BigInteger(), nullable=True),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("control_group_chat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("command_text", sa.Text(), nullable=False),
        sa.Column("command_name", sa.String(length=64), nullable=False),
        sa.Column("args_json", pg.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_summary_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("response_telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["control_group_chat_id"], ["studio_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["result_summary_id"], ["studio_chat_summaries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "control_group_chat_id",
            "source_message_id",
            name="uq_studio_control_commands_chat_source_msg",
        ),
        sa.UniqueConstraint("source_update_id", name="uq_studio_control_commands_source_update"),
    )
    op.create_index(
        "ix_studio_control_commands_source_update_id",
        "studio_control_commands",
        ["source_update_id"],
        unique=False,
    )
    op.create_index(
        "ix_studio_control_commands_source_message_id",
        "studio_control_commands",
        ["source_message_id"],
        unique=False,
    )
    op.create_index(
        "ix_studio_control_commands_control_group_chat_id",
        "studio_control_commands",
        ["control_group_chat_id"],
        unique=False,
    )
    op.create_index(
        "ix_studio_control_commands_command_name",
        "studio_control_commands",
        ["command_name"],
        unique=False,
    )
    op.create_index(
        "ix_studio_control_commands_status",
        "studio_control_commands",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_studio_control_commands_result_summary_id",
        "studio_control_commands",
        ["result_summary_id"],
        unique=False,
    )
    op.create_index(
        "ix_studio_control_commands_status_created",
        "studio_control_commands",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_studio_control_commands_cg_created",
        "studio_control_commands",
        ["control_group_chat_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_studio_control_commands_cg_created", table_name="studio_control_commands")
    op.drop_index("ix_studio_control_commands_status_created", table_name="studio_control_commands")
    op.drop_index("ix_studio_control_commands_result_summary_id", table_name="studio_control_commands")
    op.drop_index("ix_studio_control_commands_status", table_name="studio_control_commands")
    op.drop_index("ix_studio_control_commands_command_name", table_name="studio_control_commands")
    op.drop_index("ix_studio_control_commands_control_group_chat_id", table_name="studio_control_commands")
    op.drop_index("ix_studio_control_commands_source_message_id", table_name="studio_control_commands")
    op.drop_index("ix_studio_control_commands_source_update_id", table_name="studio_control_commands")
    op.drop_table("studio_control_commands")
