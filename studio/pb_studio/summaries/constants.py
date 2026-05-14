from __future__ import annotations


class SummaryType:
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"


class SummaryStatus:
    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"


class SummaryDeliveryStatus:
    """Доставка готовой сводки в Telegram control group (фаза 6d)."""

    NOT_REQUESTED = "not_requested"
    PENDING_CONTROL_GROUP_DELIVERY = "pending_control_group_delivery"
    DELIVERED_TO_CONTROL_GROUP = "delivered_to_control_group"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
