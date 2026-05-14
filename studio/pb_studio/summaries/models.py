from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pb_studio.response_queue.models import Base, JSONCompat
from pb_studio.summaries.constants import SummaryDeliveryStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioChatSummary(Base):
    """Planned/generated digest for a mirrored Telegram chat (6a planner, 6b template generation)."""

    __tablename__ = "studio_chat_summaries"
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "summary_type",
            "period_start",
            "period_end",
            name="uq_studio_chat_summaries_chat_type_period",
        ),
        Index("ix_studio_chat_summaries_chat_status", "chat_id", "status"),
        Index("ix_studio_chat_summaries_created", "created_at"),
        Index("ix_studio_chat_summaries_delivery_status", "delivery_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_role: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_status: Mapped[str] = mapped_column(
        String(64), nullable=False, default=SummaryDeliveryStatus.NOT_REQUESTED
    )
    delivery_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    destination_control_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_control_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
