from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioSlaPolicy(Base):
    """SLA policy per chat_role (client_chat / project_chat)."""

    __tablename__ = "studio_sla_policies"
    __table_args__ = (
        Index(
            "uq_studio_sla_policies_active_role",
            "chat_role",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS true"),
        ),
        Index("ix_studio_sla_policies_chat_role", "chat_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chat_role: Mapped[str] = mapped_column(String(32), nullable=False)
    first_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    followup_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    policy_tz: Mapped[str] = mapped_column("timezone", String(64), nullable=False, default="UTC")
    working_days_json: Mapped[Optional[list[Any]]] = mapped_column(JSONCompat, nullable=True)
    working_hours_start: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    working_hours_end: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    holidays_json: Mapped[Optional[list[Any]]] = mapped_column(JSONCompat, nullable=True)
    is_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    muted_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    mute_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class StudioSlaIncident(Base):
    """SLA breach / warning incident for a chat (Event Mirror messages only)."""

    __tablename__ = "studio_sla_incidents"
    __table_args__ = (
        Index(
            "uq_studio_sla_incidents_open_chat_trigger",
            "chat_id",
            "trigger_message_id",
            unique=True,
            sqlite_where=text("status = 'open' AND trigger_message_id IS NOT NULL"),
            postgresql_where=text("status = 'open' AND trigger_message_id IS NOT NULL"),
        ),
        Index("ix_studio_sla_incidents_chat_status", "chat_id", "status"),
        Index("ix_studio_sla_incidents_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_role: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_notification_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_notification_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppressed_notification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_notification_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    notification_events: Mapped[list["StudioSlaNotificationEvent"]] = relationship(
        "StudioSlaNotificationEvent", back_populates="incident", cascade="all, delete-orphan"
    )


class StudioSlaNotificationEvent(Base):
    """Audit trail for SLA Telegram notifications to control group (sent / suppressed / failed)."""

    __tablename__ = "studio_sla_notification_events"
    __table_args__ = (
        Index("ix_studio_sla_notification_events_incident_id", "incident_id"),
        Index("ix_studio_sla_notification_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_sla_incidents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    incident: Mapped["StudioSlaIncident"] = relationship("StudioSlaIncident", back_populates="notification_events")
