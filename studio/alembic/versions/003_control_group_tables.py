"""Phase 5 — control group, chat roles, system notifications.

Revision ID: 003_control_group
Revises: 002_event_mirror
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "003_control_group"
down_revision: Union[str, None] = "002_event_mirror"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studio_chats",
        sa.Column("chat_role", sa.String(length=32), server_default="unknown", nullable=False),
    )
    op.create_index("ix_studio_chats_chat_role", "studio_chats", ["chat_role"])

    op.create_table(
        "studio_control_groups",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["studio_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_control_groups_chat", "studio_control_groups", ["chat_id"])
    op.create_index(
        "uq_studio_control_groups_one_active",
        "studio_control_groups",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active IS true"),
    )

    op.create_table(
        "studio_chat_roles",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["studio_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_chat_roles_chat_created", "studio_chat_roles", ["chat_id", "created_at"])

    op.create_table(
        "studio_system_notifications",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("source_telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_studio_chat_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("lifecycle_event_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_update_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_studio_chat_id"], ["studio_chats.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lifecycle_event_id"], ["studio_chat_lifecycle_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_update_id"], ["studio_telegram_raw_updates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_sys_notif_status", "studio_system_notifications", ["status"])
    op.create_index("ix_studio_sys_notif_source_tg", "studio_system_notifications", ["source_telegram_chat_id"])
    op.create_index("ix_studio_sys_notif_kind", "studio_system_notifications", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_studio_sys_notif_kind", table_name="studio_system_notifications")
    op.drop_index("ix_studio_sys_notif_source_tg", table_name="studio_system_notifications")
    op.drop_index("ix_studio_sys_notif_status", table_name="studio_system_notifications")
    op.drop_table("studio_system_notifications")

    op.drop_index("ix_studio_chat_roles_chat_created", table_name="studio_chat_roles")
    op.drop_table("studio_chat_roles")

    op.drop_index("uq_studio_control_groups_one_active", table_name="studio_control_groups")
    op.drop_index("ix_studio_control_groups_chat", table_name="studio_control_groups")
    op.drop_table("studio_control_groups")

    op.drop_index("ix_studio_chats_chat_role", table_name="studio_chats")
    op.drop_column("studio_chats", "chat_role")
