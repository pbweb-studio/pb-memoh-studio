"""Initial Studio tables (response queue) — explicit DDL (Postgres).

Revision ID: 001_initial
Revises:
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_response_turns",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("merged_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("debounce_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_studio_turns_chat_status_seq",
        "studio_response_turns",
        ["telegram_chat_id", "status", "sequence_number"],
    )

    op.create_table(
        "studio_inbound_messages",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("turn_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.String(length=128), nullable=True),
        sa.Column("dedupe_key", sa.String(length=256), nullable=False),
        sa.Column("sender_id", sa.String(length=128), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("raw_payload", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["studio_response_turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_studio_inbound_dedupe_key"),
    )
    op.create_index("ix_studio_inbound_turn", "studio_inbound_messages", ["turn_id"])
    op.create_index("ix_studio_inbound_chat", "studio_inbound_messages", ["telegram_chat_id"])


def downgrade() -> None:
    op.drop_table("studio_inbound_messages")
    op.drop_table("studio_response_turns")
