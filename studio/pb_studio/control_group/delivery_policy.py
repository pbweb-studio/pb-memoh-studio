from __future__ import annotations

from pb_studio.control_group.constants import ChatRole


def system_notification_may_target_chat_role(role: str) -> bool:
    """Telegram system notifications must never target client/project chats."""
    try:
        cr = ChatRole(role)
    except ValueError:
        return False
    return cr is ChatRole.CONTROL_GROUP


def assert_system_notification_not_sent_to_forbidden_chat(target_role: str) -> None:
    if system_notification_may_target_chat_role(target_role):
        return
    raise ValueError(
        f"system notifications cannot be sent to chat role {target_role!r}; only control_group is allowed"
    )
