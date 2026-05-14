from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioProject(Base):
    __tablename__ = "studio_projects"
    __table_args__ = (
        Index("ix_studio_projects_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project_chats: Mapped[list["StudioProjectChat"]] = relationship(
        "StudioProjectChat", back_populates="project", cascade="all, delete-orphan"
    )


class StudioProjectChat(Base):
    __tablename__ = "studio_project_chats"
    __table_args__ = (
        UniqueConstraint("project_id", "chat_id", name="uq_studio_project_chats_project_chat"),
        Index("ix_studio_project_chats_project_id", "project_id"),
        Index("ix_studio_project_chats_chat_id", "chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_projects.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"), nullable=False
    )
    role_in_project: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    project: Mapped["StudioProject"] = relationship("StudioProject", back_populates="project_chats")
