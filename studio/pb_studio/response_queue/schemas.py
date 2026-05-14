from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field


class InboundEnqueue(BaseModel):
    """Contract: payload accepted from Event Mirror / future Telegram bridge."""

    telegram_chat_id: int = Field(..., description="Telegram chat id (negative for groups)")
    body_text: str = Field(..., min_length=1)
    telegram_message_id: str | None = None
    sender_id: str | None = None
    raw_payload: dict[str, Any] | None = None
    idempotency_key: str | None = Field(
        default=None,
        description="Used when telegram_message_id is absent; must be unique per chat.",
    )


class EnqueueResult(BaseModel):
    turn_id: UUID
    inbound_id: UUID
    dedupe_key: str
    duplicate: bool = False


class TurnDispatchResult(BaseModel):
    turn_id: UUID
    status: str
    merged_text: str


class TurnProcessor(Protocol):
    """Worker implements this to finalize a debounced turn (call Memoh later — out of scope)."""

    async def finalize_turn(
        self,
        *,
        turn_id: UUID,
        telegram_chat_id: int,
        merged_text: str,
        inbound_payloads: list[dict[str, Any] | None],
    ) -> str:
        """Return terminal TurnStatus value."""
