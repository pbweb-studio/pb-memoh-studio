from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from pb_studio.response_queue.statuses import TurnStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JSONCompat(JSON):
    """JSON on SQLite / JSONB on Postgres."""

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class ResponseTurn(Base):
    """One logical turn per burst (debounced merge of inbound lines)."""

    __tablename__ = "studio_response_turns"
    __table_args__ = (
        Index("ix_studio_turns_chat_status_seq", "telegram_chat_id", "status", "sequence_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    merged_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default=TurnStatus.PENDING.value)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    debounce_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    inbound_messages: Mapped[list["InboundMessage"]] = relationship(
        back_populates="turn",
        cascade="all, delete-orphan",
        order_by="InboundMessage.created_at",
    )


class InboundMessage(Base):
    """Single inbound line stored before / while merging into a turn."""

    __tablename__ = "studio_inbound_messages"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_studio_inbound_dedupe_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_response_turns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_message_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False)
    sender_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    turn: Mapped["ResponseTurn"] = relationship(back_populates="inbound_messages")
