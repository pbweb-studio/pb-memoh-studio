from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioControlGroup(Base):
    """At most one row with is_active=True (partial unique index + service guard)."""

    __tablename__ = "studio_control_groups"
    __table_args__ = (
        Index("ix_studio_control_groups_chat", "chat_id"),
        Index(
            "uq_studio_control_groups_one_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class StudioChatRole(Base):
    """Append-only history of chat role assignments (in addition to studio_audit_log)."""

    __tablename__ = "studio_chat_roles"
    __table_args__ = (Index("ix_studio_chat_roles_chat_created", "chat_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class StudioSystemNotification(Base):
    """System-facing notifications; never addressed to the source client chat for delivery."""

    __tablename__ = "studio_system_notifications"
    __table_args__ = (
        Index("ix_studio_sys_notif_status", "status"),
        Index("ix_studio_sys_notif_source_tg", "source_telegram_chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_studio_chat_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lifecycle_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_chat_lifecycle_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    raw_update_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_telegram_raw_updates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
