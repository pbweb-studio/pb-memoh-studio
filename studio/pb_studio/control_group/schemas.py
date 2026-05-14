from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SetControlGroupRequest(BaseModel):
    telegram_chat_id: int = Field(..., description="Telegram chat id of the control group")


class StudioChatOut(BaseModel):
    id: UUID
    telegram_chat_id: int
    chat_type: str
    title: str | None
    username: str | None
    chat_role: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ControlGroupOut(BaseModel):
    active: bool
    studio_chat: StudioChatOut | None = None


class SetChatRoleRequest(BaseModel):
    role: str


class SystemNotificationOut(BaseModel):
    id: UUID
    kind: str
    source_telegram_chat_id: int
    source_studio_chat_id: UUID | None
    status: str
    title: str | None
    payload: dict[str, Any] | None

    model_config = {"from_attributes": True}


class SystemNotificationAdminOut(BaseModel):
    id: UUID
    kind: str
    source_telegram_chat_id: int
    source_studio_chat_id: UUID | None
    status: str
    title: str | None
    body: str | None
    payload: dict[str, Any] | None
    retry_count: int
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeliverPendingResult(BaseModel):
    examined: int
    delivered: int
    failed_retryable: int
    failed_permanent: int
    skipped: int
