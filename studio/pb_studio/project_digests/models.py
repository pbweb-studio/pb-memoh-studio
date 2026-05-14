from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioProjectDigest(Base):
    __tablename__ = "studio_project_digests"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "digest_type",
            "period_start",
            "period_end",
            name="uq_studio_project_digests_project_type_period",
        ),
        Index("ix_studio_project_digests_project_created", "project_id", "created_at"),
        Index("ix_studio_project_digests_delivery_status", "delivery_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_projects.id", ondelete="CASCADE"), nullable=False
    )
    digest_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_chat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_summary_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    digest_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_requested")
    delivery_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
