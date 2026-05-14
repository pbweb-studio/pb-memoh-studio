"""Phase 11a — Studio assistant rules (storage + audit; no LLM apply).

Revision ID: 015_studio_assistant_rules
Revises: 014_studio_knowledge_chunk_embeddings
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "015_studio_assistant_rules"
down_revision: Union[str, None] = "014_studio_knowledge_chunk_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_assistant_rules",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("chat_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("created_by_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_from_message_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disable_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["studio_projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chat_id"], ["studio_chats.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_assistant_rules_scope", "studio_assistant_rules", ["scope"])
    op.create_index("ix_studio_assistant_rules_status", "studio_assistant_rules", ["status"])
    op.create_index("ix_studio_assistant_rules_project_id", "studio_assistant_rules", ["project_id"])
    op.create_index("ix_studio_assistant_rules_chat_id", "studio_assistant_rules", ["chat_id"])

    op.create_table(
        "studio_assistant_rule_audit",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rule_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("payload_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["studio_assistant_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_assistant_rule_audit_rule_id", "studio_assistant_rule_audit", ["rule_id"])
    op.create_index("ix_studio_assistant_rule_audit_created_at", "studio_assistant_rule_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_studio_assistant_rule_audit_created_at", table_name="studio_assistant_rule_audit")
    op.drop_index("ix_studio_assistant_rule_audit_rule_id", table_name="studio_assistant_rule_audit")
    op.drop_table("studio_assistant_rule_audit")
    op.drop_index("ix_studio_assistant_rules_chat_id", table_name="studio_assistant_rules")
    op.drop_index("ix_studio_assistant_rules_project_id", table_name="studio_assistant_rules")
    op.drop_index("ix_studio_assistant_rules_status", table_name="studio_assistant_rules")
    op.drop_index("ix_studio_assistant_rules_scope", table_name="studio_assistant_rules")
    op.drop_table("studio_assistant_rules")
