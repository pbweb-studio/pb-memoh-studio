from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AssistantRuleCreate(BaseModel):
    scope: str = Field(..., min_length=3, max_length=32)
    rule_text: str = Field(..., min_length=1, max_length=50_000)
    project_id: UUID | None = None
    chat_id: UUID | None = None
    source: str = Field(default="manual", max_length=32)
    metadata_json: dict[str, Any] | None = None


class AssistantRulePatch(BaseModel):
    rule_text: str | None = Field(default=None, min_length=1, max_length=50_000)
    metadata_json: dict[str, Any] | None = None


class AssistantRuleDisableBody(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class AssistantRuleOut(BaseModel):
    id: UUID
    scope: str
    project_id: UUID | None
    chat_id: UUID | None
    rule_text: str
    status: str
    source: str
    created_by_telegram_user_id: int | None
    created_from_message_id: int | None
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None
    disable_reason: str | None

    model_config = {"from_attributes": True}


class AssistantRuleAuditOut(BaseModel):
    id: UUID
    rule_id: UUID | None
    action: str
    actor_telegram_user_id: int | None
    payload_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
