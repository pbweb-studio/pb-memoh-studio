"""Initial Studio tables (response queue).

Revision ID: 001_initial
Revises:
Create Date: 2026-05-14

"""

from typing import Sequence, Union

from alembic import op

from pb_studio.response_queue.models import Base

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
