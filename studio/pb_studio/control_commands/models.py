from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioControlCommand(Base):
    """Команды из Telegram control group, зеркалированные в Studio (фаза 7a)."""

    __tablename__ = "studio_control_commands"
    __table_args__ = (
        UniqueConstraint(
            "control_group_chat_id",
            "source_message_id",
            name="uq_studio_control_commands_chat_source_msg",
        ),
        UniqueConstraint("source_update_id", name="uq_studio_control_commands_source_update"),
        Index("ix_studio_control_commands_status_created", "status", "created_at"),
        Index("ix_studio_control_commands_cg_created", "control_group_chat_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_update_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    source_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    control_group_chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    command_text: Mapped[str] = mapped_column(Text, nullable=False)
    command_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    args_json: Mapped[dict[str, Any]] = mapped_column(JSONCompat, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    result_summary_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_chat_summaries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    response_telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
