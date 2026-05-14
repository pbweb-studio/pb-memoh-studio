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
    delivery_status: str = "not_requested"
    delivery_retry_count: int = 0
    delivery_last_error: str | None = None
    delivered_at: datetime | None = None
    destination_control_group_id: UUID | None = None
    telegram_message_id: int | None = None

    model_config = {"from_attributes": True}


class DeliverPendingSummariesResult(BaseModel):
    examined: int
    delivered: int
    failed_retryable: int
    failed_permanent: int
    skipped_disabled: int
    skipped_no_token: int
    waiting_no_control_group: int
    skipped_already_delivered: int
    skipped_not_generated: int
    failed_permanent_config: int
    refused_source_equals_dest: int


class DeliverSummaryResult(BaseModel):
    id: UUID
    delivery_status: str
    telegram_message_id: int | None = None
    delivered_at: datetime | None = None
    reason: str | None = None


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


class ChatSummaryProductOut(BaseModel):
    """Ответ продуктового API 6c (без лишних полей)."""

    id: UUID
    chat_id: UUID
    chat_role: str
    summary_type: str
    period_start: datetime
    period_end: datetime
    status: str
    source_event_count: int
    summary_text: str | None
    generated_at: datetime | None


class PeriodSummaryBody(BaseModel):
    period_start: datetime
    period_end: datetime

    @model_validator(mode="after")
    def period_order(self) -> PeriodSummaryBody:
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self
