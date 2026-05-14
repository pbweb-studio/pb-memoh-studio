from __future__ import annotations

from enum import StrEnum


class ProjectDigestType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"


class ProjectDigestStatus(StrEnum):
    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"


class ProjectDigestDeliveryStatus(StrEnum):
    """Те же строки, что у сводок 6d — единый смысл для ретраев Telegram."""

    NOT_REQUESTED = "not_requested"
    PENDING_CONTROL_GROUP_DELIVERY = "pending_control_group_delivery"
    DELIVERED_TO_CONTROL_GROUP = "delivered_to_control_group"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
