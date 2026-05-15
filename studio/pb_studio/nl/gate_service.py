from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import get_control_group_chat
from pb_studio.core.config import Settings
from pb_studio.nl.constants import NlInteractionStatus, NlTriggerType
from pb_studio.nl.models import StudioNlInteraction
from pb_studio.nl.triggers import is_studio_slash_command_line

logger = logging.getLogger(__name__)


async def memoh_nl_gate(
    session: AsyncSession,
    settings: Settings,
    *,
    telegram_chat_id: int,
    message_id: int,
    update_id: int | None,
    text: str,
    raw_text: str,
    from_id: int | None,
    is_mentioned: bool,
    is_reply_to_bot: bool,
    is_bot: bool,
) -> dict[str, Any]:
    """
    Fast gate for Memoh: enqueue NL row for mention/reply in active control group.
    Returns suppress_memoh_assistant (bool), reason (str).
    """
    if not settings.studio_nl_commands_enabled:
        return {"suppress_memoh_assistant": False, "reason": "nl_disabled"}

    if is_bot:
        return {"suppress_memoh_assistant": False, "reason": "from_bot"}

    cg = await get_control_group_chat(session)
    if cg is None or cg.chat_role != ChatRole.CONTROL_GROUP.value:
        return {"suppress_memoh_assistant": False, "reason": "no_control_group"}

    if int(cg.telegram_chat_id) != int(telegram_chat_id):
        return {"suppress_memoh_assistant": False, "reason": "not_active_control_group"}

    line = (raw_text or text or "").strip()
    if not line:
        return {"suppress_memoh_assistant": False, "reason": "empty_text"}

    if is_studio_slash_command_line(line):
        return {"suppress_memoh_assistant": False, "reason": "studio_slash_command"}

    if not (is_mentioned or is_reply_to_bot):
        return {"suppress_memoh_assistant": False, "reason": "not_directed_at_bot"}

    row = StudioNlInteraction(
        source_update_id=update_id,
        source_message_id=message_id,
        control_group_chat_id=cg.id,
        sender_telegram_user_id=from_id,
        input_text=line,
        normalized_text=line.lower()[:8000],
        trigger_type=NlTriggerType.MENTION if is_mentioned else NlTriggerType.REPLY,
        mode="router_pending",
        status=NlInteractionStatus.PENDING,
        parameters_json={},
        decision_json={},
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        logger.debug("nl gate duplicate message_id=%s", message_id)
        return {"suppress_memoh_assistant": True, "reason": "already_enqueued"}

    return {"suppress_memoh_assistant": True, "reason": "nl_enqueued", "nl_interaction_id": str(row.id)}
