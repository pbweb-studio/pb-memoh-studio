from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class PlanSummaryRequest(BaseModel):
    studio_chat_id: UUID
    summary_type: Literal["daily", "weekly", "manual"]
    period_start: datetime
    period_end: datetime

    @model_validator(mode="after")
    def period_order(self) -> PlanSummaryRequest:
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class PlanSummaryResponse(BaseModel):
    id: UUID
    created: bool = Field(description="True if a new pending row was inserted")


class ChatSummaryOut(BaseModel):
    id: UUID
    chat_id: UUID
    chat_role: str
    summary_type: str
    period_start: datetime
    period_end: datetime
    status: str
    source_event_count: int
    summary_text: str | None
    metadata_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    generated_at: datetime | None
    last_error: str | None

    model_config = {"from_attributes": True}


class GeneratePendingResult(BaseModel):
    examined: int
    generated: int
    failed: int
    skipped_disabled: int
    skipped_not_pending: int


class GenerateOneResult(BaseModel):
    id: UUID
    generated: bool
    reason: str | None = None
