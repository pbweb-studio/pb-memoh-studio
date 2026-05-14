from __future__ import annotations

from enum import StrEnum


class TurnStatus(StrEnum):
    """Lifecycle of a response turn in Studio (not Telegram delivery)."""

    PENDING = "pending"
    DEBOUNCED = "debounced"
    PROCESSING = "processing"
    ANSWERED = "answered"
    IGNORED_BY_POLICY = "ignored_by_policy"
    FAILED_WITH_ERROR = "failed_with_error"
    CANCELLED_BY_NEWER_REQUEST = "cancelled_by_newer_request"
