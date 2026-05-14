from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectDigestOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    digest_type: str
    period_start: datetime
    period_end: datetime
    status: str
    source_chat_count: int
    source_summary_count: int
    digest_text: str | None
    metadata_json: dict[str, Any] | None
    delivery_status: str
    delivery_retry_count: int
    delivery_last_error: str | None
    delivered_at: datetime | None
    telegram_message_id: int | None
    created_at: datetime
    updated_at: datetime
    generated_at: datetime | None
    last_error: str | None


class ProjectDigestPeriodBody(BaseModel):
    date_a: str = Field(min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_b: str = Field(min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")


class DeliverPendingProjectDigestsResult(BaseModel):
    examined: int = 0
    delivered: int = 0
    failed_retryable: int = 0
    failed_permanent: int = 0
    skipped_already_delivered: int = 0
    skipped_not_generated: int = 0
    skipped_no_token: int = 0
    skipped_no_control_group: int = 0
    failed_permanent_config: int = 0
