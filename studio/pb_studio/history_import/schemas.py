from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HistoryImportJobOut(BaseModel):
    id: UUID
    source_type: str
    status: str
    file_name: str | None
    imported_chat_count: int
    imported_message_count: int
    skipped_count: int
    last_error: str | None
    metadata_json: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class HistoryImportTelegramJsonOut(BaseModel):
    job: HistoryImportJobOut = Field(description="Job после синхронной обработки (completed/failed)")
