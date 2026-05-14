from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TelegramRawUpdate(Base):
    """One Telegram Update as received by the mirror (dedupe by update_id)."""

    __tablename__ = "studio_telegram_raw_updates"
    __table_args__ = (UniqueConstraint("update_id", name="uq_studio_raw_updates_update_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    update_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONCompat, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    lifecycle_events: Mapped[list["ChatLifecycleEvent"]] = relationship(
        back_populates="raw_update",
    )
    messages: Mapped[list["StudioMessage"]] = relationship(
        back_populates="raw_update",
    )


class StudioChat(Base):
    __tablename__ = "studio_chats"
    __table_args__ = (UniqueConstraint("telegram_chat_id", name="uq_studio_chats_telegram_chat_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    chat_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    extra: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list["StudioMessage"]] = relationship(back_populates="chat")
    lifecycle_events: Mapped[list["ChatLifecycleEvent"]] = relationship(back_populates="chat")


class StudioTelegramUser(Base):
    __tablename__ = "studio_telegram_users"
    __table_args__ = (UniqueConstraint("telegram_user_id", name="uq_studio_tg_users_telegram_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class StudioMessage(Base):
    """Normalized Telegram message (or edited message) per chat."""

    __tablename__ = "studio_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "telegram_message_id", name="uq_studio_messages_chat_msg"),
        Index("ix_studio_messages_chat_date", "chat_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_update_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_telegram_raw_updates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_message: Mapped[dict[str, Any]] = mapped_column(JSONCompat, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    chat: Mapped["StudioChat"] = relationship(back_populates="messages")
    raw_update: Mapped[Optional["TelegramRawUpdate"]] = relationship(
        back_populates="messages",
    )


class ChatLifecycleEvent(Base):
    __tablename__ = "studio_chat_lifecycle_events"
    __table_args__ = (Index("ix_studio_lifecycle_chat_created", "chat_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"), nullable=True, index=True
    )
    raw_update_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_telegram_raw_updates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_member_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    new_member_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actor_telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    actor_is_bot: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    raw_fragment: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    chat: Mapped[Optional["StudioChat"]] = relationship(back_populates="lifecycle_events")
    raw_update: Mapped[Optional["TelegramRawUpdate"]] = relationship(
        back_populates="lifecycle_events",
    )


class AuditLog(Base):
    __tablename__ = "studio_audit_log"
    __table_args__ = (Index("ix_studio_audit_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
