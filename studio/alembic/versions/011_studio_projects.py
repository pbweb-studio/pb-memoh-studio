"""Phase 9a — projects and project↔chat binding.

Revision ID: 011_studio_projects
Revises: 010_studio_sla_notification_events
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "011_studio_projects"
down_revision: Union[str, None] = "010_studio_sla_notification_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "studio_projects",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_studio_projects_slug"),
    )
    op.create_index("ix_studio_projects_status", "studio_projects", ["status"], unique=False)

    op.create_table(
        "studio_project_chats",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("role_in_project", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["studio_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["studio_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "chat_id", name="uq_studio_project_chats_project_chat"),
    )
    op.create_index("ix_studio_project_chats_project_id", "studio_project_chats", ["project_id"], unique=False)
    op.create_index("ix_studio_project_chats_chat_id", "studio_project_chats", ["chat_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_studio_project_chats_chat_id", table_name="studio_project_chats")
    op.drop_index("ix_studio_project_chats_project_id", table_name="studio_project_chats")
    op.drop_table("studio_project_chats")
    op.drop_index("ix_studio_projects_status", table_name="studio_projects")
    op.drop_table("studio_projects")
