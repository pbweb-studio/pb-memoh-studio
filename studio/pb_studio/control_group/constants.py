from __future__ import annotations

from enum import StrEnum


class ChatRole(StrEnum):
    UNKNOWN = "unknown"
    CONTROL_GROUP = "control_group"
    CLIENT_CHAT = "client_chat"
    PROJECT_CHAT = "project_chat"
    INTERNAL_CHAT = "internal_chat"
    SERVICE_CHAT = "service_chat"


class SystemNotificationStatus(StrEnum):
    LOGGED_ONLY = "logged_only"
    PENDING_FOR_CONTROL_GROUP_DELIVERY = "pending_for_control_group_delivery"
    DELIVERED_TO_CONTROL_GROUP = "delivered_to_control_group"
    DELIVERY_FAILED = "delivery_failed"
