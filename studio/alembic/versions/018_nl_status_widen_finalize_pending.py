"""Widen studio_nl_interactions.status; finalize pending rows for single-brain migration.

Revision ID: 018_nl_status_widen_finalize_pending
Revises: 017_studio_nl_layer
Create Date: 2026-05-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_nl_status_widen_finalize_pending"
down_revision: Union[str, None] = "017_studio_nl_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FINAL_STATUS = "ignored_disabled_single_brain_migration"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else "postgresql"
    if dialect == "sqlite":
        with op.batch_alter_table("studio_nl_interactions") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.String(length=32),
                type_=sa.String(length=64),
                existing_nullable=False,
            )
    else:
        op.alter_column(
            "studio_nl_interactions",
            "status",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=False,
        )

    ts_sql = "CURRENT_TIMESTAMP" if dialect == "sqlite" else "NOW()"
    op.execute(
        sa.text(
            "UPDATE studio_nl_interactions SET status = :st, "
            "last_error = 'Archived: single-brain (Memoh+MCP).', "
            f"processed_at = {ts_sql} "
            "WHERE status = 'pending'"
        ).bindparams(st=_FINAL_STATUS)
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else "postgresql"
    op.execute(
        sa.text(
            "UPDATE studio_nl_interactions SET status = 'cancelled', "
            "last_error = 'downgrade from 018' "
            "WHERE status = :st"
        ).bindparams(st=_FINAL_STATUS)
    )
    if dialect == "sqlite":
        with op.batch_alter_table("studio_nl_interactions") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.String(length=64),
                type_=sa.String(length=32),
                existing_nullable=False,
            )
    else:
        op.alter_column(
            "studio_nl_interactions",
            "status",
            existing_type=sa.String(length=64),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
