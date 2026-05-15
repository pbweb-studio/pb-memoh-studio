"""Natural language business & learning layer tables.

Revision ID: 017_studio_nl_layer
Revises: 016_studio_history_import_jobs
Create Date: 2026-05-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "017_studio_nl_layer"
down_revision: Union[str, None] = "016_studio_history_import_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_nl_interactions",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_update_id", sa.BigInteger(), nullable=True),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "source_studio_message_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("studio_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "control_group_chat_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("studio_chats.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="router_pending"),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("parameters_json", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("decision_json", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("response_telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_nl_interactions_status", "studio_nl_interactions", ["status"])
    op.create_index("ix_studio_nl_interactions_created_at", "studio_nl_interactions", ["created_at"])
    op.create_index(
        "ix_studio_nl_interactions_cg_created",
        "studio_nl_interactions",
        ["control_group_chat_id", "created_at"],
    )
    op.create_index(
        "ix_studio_nl_interactions_status_created",
        "studio_nl_interactions",
        ["status", "created_at"],
    )
    op.create_index(
        "uq_studio_nl_interactions_cg_msg",
        "studio_nl_interactions",
        ["control_group_chat_id", "source_message_id"],
        unique=True,
        postgresql_where=sa.text("source_message_id IS NOT NULL"),
    )

    op.create_table(
        "studio_memory_items",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("source_update_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_memory_items_scope", "studio_memory_items", ["scope_type", "scope_id"])
    op.create_index("ix_studio_memory_items_status", "studio_memory_items", ["status"])
    op.create_index("ix_studio_memory_items_created_at", "studio_memory_items", ["created_at"])

    op.create_table(
        "studio_playbooks",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_examples_json", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("steps_json", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_by_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_playbooks_status", "studio_playbooks", ["status"])
    op.create_index("ix_studio_playbooks_scope", "studio_playbooks", ["scope_type", "scope_id"])
    op.create_index("ix_studio_playbooks_created_at", "studio_playbooks", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_studio_playbooks_created_at", table_name="studio_playbooks")
    op.drop_index("ix_studio_playbooks_scope", table_name="studio_playbooks")
    op.drop_index("ix_studio_playbooks_status", table_name="studio_playbooks")
    op.drop_table("studio_playbooks")

    op.drop_index("ix_studio_memory_items_created_at", table_name="studio_memory_items")
    op.drop_index("ix_studio_memory_items_status", table_name="studio_memory_items")
    op.drop_index("ix_studio_memory_items_scope", table_name="studio_memory_items")
    op.drop_table("studio_memory_items")

    op.drop_index("uq_studio_nl_interactions_cg_msg", table_name="studio_nl_interactions")
    op.drop_index("ix_studio_nl_interactions_status_created", table_name="studio_nl_interactions")
    op.drop_index("ix_studio_nl_interactions_cg_created", table_name="studio_nl_interactions")
    op.drop_index("ix_studio_nl_interactions_created_at", table_name="studio_nl_interactions")
    op.drop_index("ix_studio_nl_interactions_status", table_name="studio_nl_interactions")
    op.drop_table("studio_nl_interactions")
