from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioAssistantRule(Base):
    __tablename__ = "studio_assistant_rules"
    __table_args__ = (
        Index("ix_studio_assistant_rules_scope", "scope"),
        Index("ix_studio_assistant_rules_status", "status"),
        Index("ix_studio_assistant_rules_project_id", "project_id"),
        Index("ix_studio_assistant_rules_chat_id", "chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_projects.id", ondelete="SET NULL"), nullable=True
    )
    chat_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_chats.id", ondelete="SET NULL"), nullable=True
    )
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    created_by_telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_from_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    disabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    disable_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class StudioAssistantRuleAudit(Base):
    __tablename__ = "studio_assistant_rule_audit"
    __table_args__ = (
        Index("ix_studio_assistant_rule_audit_rule_id", "rule_id"),
        Index("ix_studio_assistant_rule_audit_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_assistant_rules.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
