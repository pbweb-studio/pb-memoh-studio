from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import _audit
from pb_studio.control_group.telegram_outbound import telegram_send_message
from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.sla.constants import SlaIncidentStatus, SlaSeverity
from pb_studio.sla.calendar import calculate_due_at, policy_blocks_new_incidents
from pb_studio.sla.models import StudioSlaIncident, StudioSlaPolicy
from pb_studio.sla.notifications import SendMessageFn, dispatch_sla_notifications

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_user_incoming_message(raw: dict[str, Any]) -> bool:
    from_obj = raw.get("from")
    if not isinstance(from_obj, dict):
        return False
    if bool(from_obj.get("is_bot")):
        return False
    return True


def _is_bot_message(raw: dict[str, Any]) -> bool:
    from_obj = raw.get("from")
    if not isinstance(from_obj, dict):
        return False
    return bool(from_obj.get("is_bot"))


def _message_is_after(a: StudioMessage, b: StudioMessage) -> bool:
    ad = _as_utc(a.date)
    bd = _as_utc(b.date)
    if ad != bd:
        return ad > bd
    return a.telegram_message_id > b.telegram_message_id


def find_tail_unanswered_user_message(messages_asc: list[StudioMessage]) -> StudioMessage | None:
    for idx in range(len(messages_asc) - 1, -1, -1):
        m = messages_asc[idx]
        if not _is_user_incoming_message(m.raw_message):
            continue
        has_bot_after = any(
            _is_bot_message(messages_asc[j].raw_message) for j in range(idx + 1, len(messages_asc))
        )
        if not has_bot_after:
            return m
    return None


async def _effective_policy_row(
    session: AsyncSession, chat_role: str
) -> StudioSlaPolicy | None:
    return await session.scalar(
        select(StudioSlaPolicy).where(
            StudioSlaPolicy.chat_role == chat_role,
            StudioSlaPolicy.is_active.is_(True),
        )
    )


def effective_first_response_minutes(settings: Settings, policy: StudioSlaPolicy | None) -> int:
    if policy is not None:
        return max(1, int(policy.first_response_minutes))
    return max(1, int(settings.studio_sla_default_first_response_minutes))


async def _load_messages(session: AsyncSession, chat_id: UUID) -> list[StudioMessage]:
    stmt = (
        select(StudioMessage)
        .where(StudioMessage.chat_id == chat_id)
        .order_by(StudioMessage.date.asc(), StudioMessage.telegram_message_id.asc())
    )
    return list((await session.scalars(stmt)).all())


async def _has_bot_reply_after(session: AsyncSession, chat_id: UUID, trigger: StudioMessage) -> bool:
    msgs = await _load_messages(session, chat_id)
    return any(
        _is_bot_message(m.raw_message) and _message_is_after(m, trigger) for m in msgs
    )


async def resolve_open_incidents_answered(session: AsyncSession, *, now: datetime) -> int:
    open_rows = (
        await session.scalars(
            select(StudioSlaIncident).where(StudioSlaIncident.status == SlaIncidentStatus.OPEN.value)
        )
    ).all()
    n = 0
    for inc in open_rows:
        if inc.trigger_message_id is None:
            continue
        trig = await session.get(StudioMessage, inc.trigger_message_id)
        if trig is None or trig.chat_id != inc.chat_id:
            inc.status = SlaIncidentStatus.RESOLVED.value
            inc.resolved_at = now
            inc.updated_at = now
            n += 1
            continue
        if await _has_bot_reply_after(session, inc.chat_id, trig):
            inc.status = SlaIncidentStatus.RESOLVED.value
            inc.resolved_at = now
            inc.updated_at = now
            base = dict(inc.metadata_json or {})
            base["resolved_reason"] = "bot_reply_after_trigger"
            inc.metadata_json = base
            n += 1
    return n


async def resolve_stale_open_incidents(
    session: AsyncSession,
    *,
    chat_id: UUID,
    current_tail_id: UUID | None,
    now: datetime,
) -> int:
    open_rows = (
        await session.scalars(
            select(StudioSlaIncident).where(
                StudioSlaIncident.chat_id == chat_id,
                StudioSlaIncident.status == SlaIncidentStatus.OPEN.value,
            )
        )
    ).all()
    n = 0
    for inc in open_rows:
        tid = inc.trigger_message_id
        if current_tail_id is None:
            if tid is not None:
                inc.status = SlaIncidentStatus.RESOLVED.value
                inc.resolved_at = now
                inc.updated_at = now
                base = dict(inc.metadata_json or {})
                base["resolved_reason"] = "no_unanswered_tail"
                inc.metadata_json = base
                n += 1
            continue
        if tid != current_tail_id:
            inc.status = SlaIncidentStatus.RESOLVED.value
            inc.resolved_at = now
            inc.updated_at = now
            base = dict(inc.metadata_json or {})
            base["resolved_reason"] = "superseded_by_newer_inbound"
            inc.metadata_json = base
            n += 1
    return n


async def run_sla_detection_cycle(
    session: AsyncSession,
    settings: Settings,
    *,
    send_message: SendMessageFn | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    send_message = send_message or telegram_send_message
    now = now or utcnow()
    counts: dict[str, int] = {
        "chats_scanned": 0,
        "resolved_answered": 0,
        "resolved_stale": 0,
        "created": 0,
        "duplicate_skipped": 0,
        "skipped_disabled": 0,
        "sla_notify_sent": 0,
        "sla_notify_suppressed": 0,
        "sla_notify_failed": 0,
        "sla_notify_skipped": 0,
        "sla_notify_digest": 0,
    }
    if not settings.studio_sla_enabled:
        counts["skipped_disabled"] = 1
        logger.info("SLA detection skipped: STUDIO_SLA_ENABLED=false")
        return counts

    notify_queue: list[tuple[StudioSlaIncident, StudioChat, StudioSlaPolicy | None, bool]] = []

    counts["resolved_answered"] = await resolve_open_incidents_answered(session, now=now)

    roles = (ChatRole.CLIENT_CHAT.value, ChatRole.PROJECT_CHAT.value)
    chats = (await session.scalars(select(StudioChat).where(StudioChat.chat_role.in_(roles)))).all()

    for chat in chats:
        counts["chats_scanned"] += 1
        policy_row = await _effective_policy_row(session, chat.chat_role)
        minutes = effective_first_response_minutes(settings, policy_row)
        msgs = await _load_messages(session, chat.id)
        tail = find_tail_unanswered_user_message(msgs)
        tail_id = tail.id if tail else None
        counts["resolved_stale"] += await resolve_stale_open_incidents(
            session, chat_id=chat.id, current_tail_id=tail_id, now=now
        )

        if tail is None:
            continue

        due_at = calculate_due_at(_as_utc(tail.date), policy_row, settings)

        existing = await session.scalar(
            select(StudioSlaIncident).where(
                StudioSlaIncident.chat_id == chat.id,
                StudioSlaIncident.trigger_message_id == tail.id,
                StudioSlaIncident.status == SlaIncidentStatus.OPEN.value,
            )
        )
        if existing is not None:
            notify_queue.append((existing, chat, policy_row, False))
            continue

        if policy_blocks_new_incidents(policy_row, now):
            continue

        if _as_utc(now) < due_at:
            continue

        severity = SlaSeverity.BREACHED.value
        meta: dict[str, Any] = {
            "telegram_chat_id": int(chat.telegram_chat_id),
            "first_response_minutes": minutes,
        }
        if policy_row is not None:
            meta["policy_id"] = str(policy_row.id)

        inc = StudioSlaIncident(
            chat_id=chat.id,
            chat_role=chat.chat_role,
            trigger_message_id=tail.id,
            status=SlaIncidentStatus.OPEN.value,
            severity=severity,
            due_at=due_at,
            detected_at=now,
            notification_count=0,
            metadata_json=meta,
        )
        session.add(inc)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            counts["duplicate_skipped"] += 1
            await session.expunge(inc)
            continue

        counts["created"] += 1
        await _audit(
            session,
            action="sla.incident_created",
            entity_type="studio_sla_incident",
            entity_id=str(inc.id),
            payload={"chat_id": str(chat.id), "trigger_message_id": str(tail.id)},
        )
        notify_queue.append((inc, chat, policy_row, False))

    notify_counts = await dispatch_sla_notifications(
        session, settings, notify_queue, send_message, now=now
    )
    counts.update(notify_counts)

    return counts


async def run_sla_detection_standalone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        out = await run_sla_detection_cycle(session, settings)
        await session.commit()
    return out
