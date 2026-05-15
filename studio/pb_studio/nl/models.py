from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioNlInteraction(Base):
    """One NL request from control group (gate or alias scan)."""

    __tablename__ = "studio_nl_interactions"
    __table_args__ = (
        Index("ix_studio_nl_interactions_created_at", "created_at"),
        Index("ix_studio_nl_interactions_cg_created", "control_group_chat_id", "created_at"),
        Index("ix_studio_nl_interactions_status_created", "status", "created_at"),
        Index(
            "uq_studio_nl_interactions_cg_msg",
            "control_group_chat_id",
            "source_message_id",
            unique=True,
            postgresql_where=text("source_message_id IS NOT NULL"),
            sqlite_where=text("source_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_update_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    source_studio_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    control_group_chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="router_pending")
    intent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONCompat, nullable=False, default=dict)
    decision_json: Mapped[dict[str, Any]] = mapped_column(JSONCompat, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending", index=True)
    reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class StudioMemoryItem(Base):
    """Short facts / preferences (NL learning), not full KB documents."""

    __tablename__ = "studio_memory_items"
    __table_args__ = (
        Index("ix_studio_memory_items_scope", "scope_type", "scope_id"),
        Index("ix_studio_memory_items_status", "status"),
        Index("ix_studio_memory_items_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_update_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_by_telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class StudioPlaybook(Base):
    """Workflow drafts / playbooks from NL learning."""

    __tablename__ = "studio_playbooks"
    __table_args__ = (
        Index("ix_studio_playbooks_status", "status"),
        Index("ix_studio_playbooks_scope", "scope_type", "scope_id"),
        Index("ix_studio_playbooks_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    trigger_examples_json: Mapped[Any] = mapped_column(JSONCompat, nullable=False)
    steps_json: Mapped[Any] = mapped_column(JSONCompat, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_by_telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
