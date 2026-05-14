"""Phase 8a — SLA policies and incidents (Studio DB, Event Mirror messages).

Revision ID: 008_studio_sla
Revises: 007_studio_control_commands
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "008_studio_sla"
down_revision: Union[str, None] = "007_studio_control_commands"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_sla_policies",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_role", sa.String(length=32), nullable=False),
        sa.Column("first_response_minutes", sa.Integer(), nullable=False),
        sa.Column("followup_minutes", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_sla_policies_chat_role", "studio_sla_policies", ["chat_role"], unique=False)
    op.create_index(
        "uq_studio_sla_policies_active_role",
        "studio_sla_policies",
        ["chat_role"],
        unique=True,
        postgresql_where=sa.text("is_active IS true"),
    )

    op.create_table(
        "studio_sla_incidents",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_role", sa.String(length=32), nullable=False),
        sa.Column("trigger_message_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notification_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["studio_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trigger_message_id"], ["studio_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studio_sla_incidents_chat_id", "studio_sla_incidents", ["chat_id"], unique=False)
    op.create_index(
        "ix_studio_sla_incidents_trigger_message_id",
        "studio_sla_incidents",
        ["trigger_message_id"],
        unique=False,
    )
    op.create_index(
        "ix_studio_sla_incidents_chat_status",
        "studio_sla_incidents",
        ["chat_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_studio_sla_incidents_status_created",
        "studio_sla_incidents",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_studio_sla_incidents_open_chat_trigger",
        "studio_sla_incidents",
        ["chat_id", "trigger_message_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open' AND trigger_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_studio_sla_incidents_open_chat_trigger", table_name="studio_sla_incidents")
    op.drop_index("ix_studio_sla_incidents_status_created", table_name="studio_sla_incidents")
    op.drop_index("ix_studio_sla_incidents_chat_status", table_name="studio_sla_incidents")
    op.drop_index("ix_studio_sla_incidents_trigger_message_id", table_name="studio_sla_incidents")
    op.drop_index("ix_studio_sla_incidents_chat_id", table_name="studio_sla_incidents")
    op.drop_table("studio_sla_incidents")
    op.drop_index("uq_studio_sla_policies_active_role", table_name="studio_sla_policies")
    op.drop_index("ix_studio_sla_policies_chat_role", table_name="studio_sla_policies")
    op.drop_table("studio_sla_policies")
