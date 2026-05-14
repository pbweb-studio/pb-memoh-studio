from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from pb_studio.response_queue.schemas import EnqueueResult


class TelegramEventIngestResponse(BaseModel):
    ok: bool = True
    telegram_raw_update_id: UUID
    duplicate: bool = False
    """When True, body was not re-normalized; same update_id as first request."""
    enqueue: EnqueueResult | None = Field(
        default=None,
        description="Present only when mirror enqueue is enabled and a user text message was queued.",
    )
    detail: str | None = None


class MirrorQueueContract(BaseModel):
    """Documented mapping from mirrored Telegram message → InboundEnqueue (no Memoh)."""

    telegram_chat_id: int
    body_text: str
    telegram_message_id: str
    sender_id: str | None = None
    raw_payload: dict[str, Any] | None = None
