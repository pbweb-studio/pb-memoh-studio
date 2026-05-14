"""Phase 8c — SLA notification audit, rate-limit, digest batching.

Revision ID: 010_studio_sla_notification_events
Revises: 009_studio_sla_working_hours
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "010_studio_sla_notification_events"
down_revision: Union[str, None] = "009_studio_sla_working_hours"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studio_sla_incidents",
        sa.Column("next_notification_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "studio_sla_incidents",
        sa.Column(
            "suppressed_notification_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "studio_sla_incidents",
        sa.Column("last_notification_reason", sa.String(length=128), nullable=True),
    )

    op.create_table(
        "studio_sla_notification_events",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("incident_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["studio_sla_incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_studio_sla_notification_events_incident_id",
        "studio_sla_notification_events",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_studio_sla_notification_events_created_at",
        "studio_sla_notification_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_studio_sla_notification_events_created_at", table_name="studio_sla_notification_events")
    op.drop_index("ix_studio_sla_notification_events_incident_id", table_name="studio_sla_notification_events")
    op.drop_table("studio_sla_notification_events")
    op.drop_column("studio_sla_incidents", "last_notification_reason")
    op.drop_column("studio_sla_incidents", "suppressed_notification_count")
    op.drop_column("studio_sla_incidents", "next_notification_at")
