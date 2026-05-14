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
    next_notification_at: datetime | None
    notification_count: int
    suppressed_notification_count: int = 0
    last_notification_reason: str | None
    last_error: str | None
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class SlaNotificationEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    incident_id: UUID
    status: str
    reason: str | None
    telegram_message_id: int | None
    error: str | None
    payload_json: dict[str, Any] | None
    created_at: datetime


class SlaPolicyOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    chat_role: str
    first_response_minutes: int
    followup_minutes: int | None
    is_active: bool
    policy_tz: str = "UTC"
    working_days_json: list[Any] | None = None
    working_hours_start: str | None = None
    working_hours_end: str | None = None
    holidays_json: list[Any] | None = None
    is_muted: bool = False
    muted_until: datetime | None = None
    mute_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class SlaPolicyCreate(BaseModel):
    chat_role: str = Field(min_length=1, max_length=32)
    first_response_minutes: int = Field(ge=1, le=10_080)
    followup_minutes: int | None = Field(default=None, ge=1, le=10_080)
    is_active: bool = True
    policy_tz: str | None = Field(default=None, max_length=64)
    working_days_json: list[int] | None = None
    working_hours_start: str | None = Field(default=None, max_length=8)
    working_hours_end: str | None = Field(default=None, max_length=8)
    holidays_json: list[str] | None = None


class SlaPolicyPatch(BaseModel):
    first_response_minutes: int | None = Field(default=None, ge=1, le=10_080)
    followup_minutes: int | None = Field(default=None, ge=1, le=10_080)
    is_active: bool | None = None
    policy_tz: str | None = Field(default=None, max_length=64)
    working_days_json: list[int] | None = None
    working_hours_start: str | None = Field(default=None, max_length=8)
    working_hours_end: str | None = Field(default=None, max_length=8)
    holidays_json: list[str] | None = None


class SlaPolicyMuteBody(BaseModel):
    muted_until: datetime | None = None
    mute_reason: str | None = Field(default=None, max_length=2000)


class SlaDetectResponse(BaseModel):
    chats_scanned: int
    resolved_answered: int
    resolved_stale: int
    created: int
    duplicate_skipped: int
    skipped_disabled: int
    sla_notify_sent: int = 0
    sla_notify_suppressed: int = 0
    sla_notify_failed: int = 0
    sla_notify_skipped: int = 0
    sla_notify_digest: int = 0


class SlaManualNotifyResponse(BaseModel):
    ok: bool
    error: str | None = None
    sla_notify_sent: int = 0
    sla_notify_suppressed: int = 0
    sla_notify_failed: int = 0
    sla_notify_skipped: int = 0
    sla_notify_digest: int = 0
