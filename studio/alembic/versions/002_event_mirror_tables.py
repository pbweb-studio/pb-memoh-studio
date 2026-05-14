"""Event Mirror tables (Telegram JSON → Studio DB).

Revision ID: 002_event_mirror
Revises: 001_initial
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "002_event_mirror"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_telegram_raw_updates",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", pg.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("update_id", name="uq_studio_raw_updates_update_id"),
    )
    op.create_index("ix_studio_telegram_raw_updates_update_id", "studio_telegram_raw_updates", ["update_id"])

    op.create_table(
        "studio_chats",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_type", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("extra", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_chat_id", name="uq_studio_chats_telegram_chat_id"),
    )
    op.create_index("ix_studio_chats_telegram_chat_id", "studio_chats", ["telegram_chat_id"])

    op.create_table(
        "studio_telegram_users",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id", name="uq_studio_tg_users_telegram_user_id"),
    )
    op.create_index("ix_studio_telegram_users_telegram_user_id", "studio_telegram_users", ["telegram_user_id"])

    op.create_table(
        "studio_messages",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_update_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("raw_message", pg.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["studio_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_update_id"], ["studio_telegram_raw_updates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "telegram_message_id", name="uq_studio_messages_chat_msg"),
    )
    op.create_index("ix_studio_messages_chat_id", "studio_messages", ["chat_id"])
    op.create_index("ix_studio_messages_raw_update_id", "studio_messages", ["raw_update_id"])
    op.create_index("ix_studio_messages_chat_date", "studio_messages", ["chat_id", "date"])

    op.create_table(
        "studio_chat_lifecycle_events",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_update_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("old_member_status", sa.String(length=64), nullable=True),
        sa.Column("new_member_status", sa.String(length=64), nullable=True),
        sa.Column("actor_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_is_bot", sa.Boolean(), nullable=True),
        sa.Column("raw_fragment", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["studio_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_update_id"], ["studio_telegram_raw_updates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_lifecycle_chat_created", "studio_chat_lifecycle_events", ["chat_id", "created_at"])
    op.create_index("ix_studio_lifecycle_event_type", "studio_chat_lifecycle_events", ["event_type"])
    op.create_index("ix_studio_lifecycle_raw_update_id", "studio_chat_lifecycle_events", ["raw_update_id"])

    op.create_table(
        "studio_audit_log",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("payload", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_audit_created", "studio_audit_log", ["created_at"])
    op.create_index("ix_studio_audit_action", "studio_audit_log", ["action"])


def downgrade() -> None:
    op.drop_table("studio_audit_log")
    op.drop_table("studio_chat_lifecycle_events")
    op.drop_table("studio_messages")
    op.drop_table("studio_telegram_users")
    op.drop_table("studio_chats")
    op.drop_table("studio_telegram_raw_updates")
