from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import not_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import get_control_group_chat
from pb_studio.core.config import Settings
from pb_studio.event_mirror.models import StudioMessage
from pb_studio.nl.constants import NlInteractionStatus, NlTriggerType
from pb_studio.nl.models import StudioNlInteraction
from pb_studio.nl.triggers import is_studio_slash_command_line, strip_alias_prefix
from pb_studio.nl.turn_input import nl_turn_router_input

logger = logging.getLogger(__name__)


def _sender_is_bot(raw: dict[str, Any]) -> bool:
    from_obj = raw.get("from")
    if not isinstance(from_obj, dict):
        return False
    return bool(from_obj.get("is_bot"))


def _sender_id(raw: dict[str, Any]) -> int | None:
    from_obj = raw.get("from")
    if not isinstance(from_obj, dict):
        return None
    uid = from_obj.get("id")
    return int(uid) if isinstance(uid, int) else None


async def scan_mirror_for_nl_aliases(
    session: AsyncSession,
    settings: Settings,
    *,
    batch_limit: int | None = None,
) -> dict[str, int]:
    counts = {"scanned": 0, "inserted": 0, "skipped": 0, "skipped_disabled": 0}
    if not settings.studio_nl_commands_enabled:
        counts["skipped_disabled"] = 1
        return counts

    cg = await get_control_group_chat(session)
    if cg is None or cg.chat_role != ChatRole.CONTROL_GROUP.value:
        return counts

    lim = min(max(batch_limit or settings.studio_control_commands_max_batch, 1), 200)
    dup_exists = (
        select(StudioNlInteraction.id)
        .where(
            StudioNlInteraction.control_group_chat_id == cg.id,
            StudioNlInteraction.source_message_id == StudioMessage.telegram_message_id,
        )
        .exists()
    )
    stmt = (
        select(StudioMessage)
        .where(
            StudioMessage.chat_id == cg.id,
            StudioMessage.text.isnot(None),
            not_(dup_exists),
        )
        .order_by(StudioMessage.date.asc())
        .limit(lim)
    )
    rows = list((await session.scalars(stmt)).all())
    for msg in rows:
        counts["scanned"] += 1
        if _sender_is_bot(msg.raw_message):
            counts["skipped"] += 1
            continue
        text = (msg.text or "").strip()
        if not text:
            counts["skipped"] += 1
            continue
        if is_studio_slash_command_line(text):
            counts["skipped"] += 1
            continue
        stripped, had_alias = strip_alias_prefix(text, settings)
        if not had_alias:
            counts["skipped"] += 1
            continue
        if not stripped:
            counts["skipped"] += 1
            continue
        stripped = nl_turn_router_input(stripped, settings)
        if not stripped:
            counts["skipped"] += 1
            continue

        src_update_id: int | None = None
        raw_upd = getattr(msg, "raw_update_id", None)
        if raw_upd is not None:
            from pb_studio.event_mirror.models import TelegramRawUpdate

            ru = await session.get(TelegramRawUpdate, raw_upd)
            if ru is not None:
                src_update_id = int(ru.update_id)

        sid = _sender_id(msg.raw_message)
        row = StudioNlInteraction(
            source_update_id=src_update_id,
            source_message_id=int(msg.telegram_message_id),
            control_group_chat_id=cg.id,
            sender_telegram_user_id=sid,
            input_text=stripped,
            normalized_text=stripped.lower()[:8000],
            trigger_type=NlTriggerType.ALIAS,
            mode="router_pending",
            status=NlInteractionStatus.PENDING,
            parameters_json={"alias_stripped": True},
            decision_json={},
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
            counts["inserted"] += 1
        except IntegrityError:
            counts["skipped"] += 1
    return counts
