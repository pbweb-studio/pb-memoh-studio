"""Phase 8b — SLA working hours, timezone, mute on policies.

Revision ID: 009_studio_sla_working_hours
Revises: 008_studio_sla
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "009_studio_sla_working_hours"
down_revision: Union[str, None] = "008_studio_sla"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studio_sla_policies",
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
    )
    op.add_column("studio_sla_policies", sa.Column("working_days_json", pg.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("studio_sla_policies", sa.Column("working_hours_start", sa.String(length=8), nullable=True))
    op.add_column("studio_sla_policies", sa.Column("working_hours_end", sa.String(length=8), nullable=True))
    op.add_column("studio_sla_policies", sa.Column("holidays_json", pg.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        "studio_sla_policies",
        sa.Column("is_muted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("studio_sla_policies", sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("studio_sla_policies", sa.Column("mute_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("studio_sla_policies", "mute_reason")
    op.drop_column("studio_sla_policies", "muted_until")
    op.drop_column("studio_sla_policies", "is_muted")
    op.drop_column("studio_sla_policies", "holidays_json")
    op.drop_column("studio_sla_policies", "working_hours_end")
    op.drop_column("studio_sla_policies", "working_hours_start")
    op.drop_column("studio_sla_policies", "working_days_json")
    op.drop_column("studio_sla_policies", "timezone")
