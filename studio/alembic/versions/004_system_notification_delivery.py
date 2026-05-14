"""System notification delivery columns (phase 5b).

Revision ID: 004_system_notification_delivery
Revises: 003_control_group
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_system_notification_delivery"
down_revision: Union[str, None] = "003_control_group"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studio_system_notifications",
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("studio_system_notifications", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("studio_system_notifications", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "studio_system_notifications",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_studio_sys_notif_status_created",
        "studio_system_notifications",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_studio_sys_notif_status_created", table_name="studio_system_notifications")
    op.drop_column("studio_system_notifications", "updated_at")
    op.drop_column("studio_system_notifications", "delivered_at")
    op.drop_column("studio_system_notifications", "last_error")
    op.drop_column("studio_system_notifications", "retry_count")
