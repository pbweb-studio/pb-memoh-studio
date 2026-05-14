from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SlaIncidentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    chat_id: UUID
    chat_role: str
    trigger_message_id: UUID | None
    status: str
    severity: str
    due_at: datetime
    detected_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    last_notification_at: datetime | None
    notification_count: int
    last_error: str | None
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class SlaPolicyOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    chat_role: str
    first_response_minutes: int
    followup_minutes: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SlaPolicyCreate(BaseModel):
    chat_role: str = Field(min_length=1, max_length=32)
    first_response_minutes: int = Field(ge=1, le=10_080)
    followup_minutes: int | None = Field(default=None, ge=1, le=10_080)
    is_active: bool = True


class SlaDetectResponse(BaseModel):
    chats_scanned: int
    resolved_answered: int
    resolved_stale: int
    created: int
    duplicate_skipped: int
    skipped_disabled: int
