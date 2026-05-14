from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ControlCommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_update_id: int | None
    source_message_id: int | None
    control_group_chat_id: UUID
    command_text: str
    command_name: str
    args_json: dict[str, Any]
    status: str
    result_summary_id: UUID | None
    response_telegram_message_id: int | None
    last_error: str | None
    created_at: datetime
    processed_at: datetime | None


class ControlCommandsProcessResponse(BaseModel):
    scan: dict[str, int] = Field(default_factory=dict)
    process: dict[str, int] = Field(default_factory=dict)
