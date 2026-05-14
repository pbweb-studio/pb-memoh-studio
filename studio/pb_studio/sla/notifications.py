from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import _audit, get_control_group_chat
from pb_studio.control_group.telegram_outbound import redact_secrets
from pb_studio.core.config import Settings
from pb_studio.event_mirror.models import StudioChat
from pb_studio.sla.constants import SlaNotificationEventStatus
from pb_studio.sla.models import StudioSlaIncident, StudioSlaNotificationEvent, StudioSlaPolicy

SendMessageFn = Callable[..., Awaitable[tuple[bool, int | None, str, int | None]]]


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def effective_followup_minutes(policy: StudioSlaPolicy | None) -> int | None:
    if policy is None or policy.followup_minutes is None:
        return None
    v = int(policy.followup_minutes)
    return v if v > 0 else None


def notification_interval_minutes(settings: Settings, policy: StudioSlaPolicy | None) -> int:
    cd = max(1, int(settings.studio_sla_notification_cooldown_minutes))
    fu = effective_followup_minutes(policy)
    if fu is None:
        return cd
    return max(cd, fu)


class _Decision(StrEnum):
    SEND = "send"
    SUPPRESS_COOLDOWN = "suppress_cooldown"
    SUPPRESS_MAX = "suppress_max"
    SKIP_NO_TOKEN = "skip_no_token"
    SKIP_NO_CG = "skip_no_cg"
    SKIP_SAME_CHAT = "skip_same_chat"


@dataclass(frozen=True)
class _NotifyItem:
    incident: StudioSlaIncident
    source_chat: StudioChat
    policy: StudioSlaPolicy | None
    force: bool


def _safe_payload(data: dict[str, Any], token: str) -> dict[str, Any]:
    try:
        dumped = json.dumps(data, sort_keys=True, default=str)
    except TypeError:
        return {"redacted": True}
    if token and token in dumped:
        return {"redacted": True}
    return data


def _single_line_text(incident: StudioSlaIncident, source_chat: StudioChat) -> str:
    return (
        f"SLA: чат {source_chat.telegram_chat_id} ({incident.chat_role}), "
        f"нарушение first response, incident={incident.id}"
    )


def _build_digest_body(
    items: list[tuple[StudioSlaIncident, StudioChat]],
    settings: Settings,
) -> str:
    max_items = max(1, int(settings.studio_sla_notification_digest_max_items))
    max_len = max(3, int(settings.studio_sla_notification_text_max_len))
    total = len(items)
    head = items[:max_items]
    lines = [f"SLA digest ({total} инцидентов):"]
    for idx, (inc, ch) in enumerate(head, start=1):
        lines.append(f"{idx}. {_single_line_text(inc, ch)}")
    rest = total - len(head)
    if rest > 0:
        lines.append(f"и ещё {rest} инцидентов")
    text = "\n".join(lines)
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3].rstrip() + "..."


def _classify(
    item: _NotifyItem,
    *,
    settings: Settings,
    now: datetime,
    dest: StudioChat | None,
    token_ok: bool,
) -> _Decision:
    if not token_ok:
        return _Decision.SKIP_NO_TOKEN
    if dest is None or dest.chat_role != ChatRole.CONTROL_GROUP.value:
        return _Decision.SKIP_NO_CG
    if int(dest.telegram_chat_id) == int(item.source_chat.telegram_chat_id):
        return _Decision.SKIP_SAME_CHAT

    max_n = max(0, int(settings.studio_sla_max_notifications_per_incident))
    count = int(item.incident.notification_count)
    if max_n == 0 or count >= max_n:
        return _Decision.SUPPRESS_MAX

    if int(item.incident.notification_count) == 0:
        return _Decision.SEND

    if item.force:
        return _Decision.SEND

    nxt = item.incident.next_notification_at
    if nxt is not None and _as_utc(now) < _as_utc(nxt):
        return _Decision.SUPPRESS_COOLDOWN

    return _Decision.SEND


async def _append_event(
    session: AsyncSession,
    *,
    incident_id: UUID,
    status: str,
    reason: str | None,
    telegram_message_id: int | None,
    error: str | None,
    payload_json: dict[str, Any] | None,
    now: datetime,
) -> None:
    session.add(
        StudioSlaNotificationEvent(
            incident_id=incident_id,
            status=status,
            reason=reason,
            telegram_message_id=telegram_message_id,
            error=error,
            payload_json=payload_json,
            created_at=now,
        )
    )


async def dispatch_sla_notifications(
    session: AsyncSession,
    settings: Settings,
    items: list[tuple[StudioSlaIncident, StudioChat, StudioSlaPolicy | None, bool]],
    send_message: SendMessageFn,
    *,
    now: datetime,
) -> dict[str, int]:
    counts = {
        "sla_notify_sent": 0,
        "sla_notify_suppressed": 0,
        "sla_notify_failed": 0,
        "sla_notify_skipped": 0,
        "sla_notify_digest": 0,
    }
    if not items:
        return counts

    token = (settings.telegram_bot_token or "").strip()
    token_ok = bool(token)
    dest = await get_control_group_chat(session) if token_ok else None

    planned: list[tuple[_NotifyItem, _Decision]] = []
    for inc, src, pol, force in items:
        ni = _NotifyItem(incident=inc, source_chat=src, policy=pol, force=force)
        planned.append((ni, _classify(ni, settings=settings, now=now, dest=dest, token_ok=token_ok)))

    for ni, dec in planned:
        inc = ni.incident
        if dec == _Decision.SKIP_NO_TOKEN or dec == _Decision.SKIP_NO_CG or dec == _Decision.SKIP_SAME_CHAT:
            counts["sla_notify_skipped"] += 1
            continue
        if dec == _Decision.SUPPRESS_MAX:
            counts["sla_notify_suppressed"] += 1
            inc.suppressed_notification_count = int(inc.suppressed_notification_count or 0) + 1
            inc.last_notification_reason = "max_notifications"
            inc.updated_at = now
            await _append_event(
                session,
                incident_id=inc.id,
                status=SlaNotificationEventStatus.SUPPRESSED.value,
                reason="max_notifications",
                telegram_message_id=None,
                error=None,
                payload_json=_safe_payload({"kind": "suppress"}, token),
                now=now,
            )
            await _audit(
                session,
                action="sla.notification_suppressed",
                entity_type="studio_sla_incident",
                entity_id=str(inc.id),
                payload={"reason": "max_notifications"},
            )
            continue
        if dec == _Decision.SUPPRESS_COOLDOWN:
            counts["sla_notify_suppressed"] += 1
            inc.suppressed_notification_count = int(inc.suppressed_notification_count or 0) + 1
            inc.last_notification_reason = "cooldown"
            inc.updated_at = now
            await _append_event(
                session,
                incident_id=inc.id,
                status=SlaNotificationEventStatus.SUPPRESSED.value,
                reason="cooldown",
                telegram_message_id=None,
                error=None,
                payload_json=_safe_payload(
                    {
                        "kind": "suppress",
                        "next_notification_at": inc.next_notification_at.isoformat()
                        if inc.next_notification_at
                        else None,
                    },
                    token,
                ),
                now=now,
            )
            await _audit(
                session,
                action="sla.notification_suppressed",
                entity_type="studio_sla_incident",
                entity_id=str(inc.id),
                payload={"reason": "cooldown"},
            )
            continue

    send_list = [ni for ni, dec in planned if dec == _Decision.SEND]
    if not send_list:
        return counts

    send_list.sort(key=lambda x: str(x.incident.id))
    timeout_s = max(0.5, settings.studio_telegram_send_timeout_ms / 1000.0)
    digest = len(send_list) > 1
    assert dest is not None
    if digest:
        text = _build_digest_body([(x.incident, x.source_chat) for x in send_list], settings)
        counts["sla_notify_digest"] = 1
    else:
        text = _single_line_text(send_list[0].incident, send_list[0].source_chat)
        max_len = max(3, int(settings.studio_sla_notification_text_max_len))
        if len(text) > max_len:
            text = text[: max_len - 3].rstrip() + "..."

    mid: int | None = None
    http_status: int | None = None
    err_detail = ""
    try:
        ok, http_status, err_detail, mid = await send_message(
            bot_token=token,
            chat_id=int(dest.telegram_chat_id),
            text=text,
            timeout_seconds=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        err_detail = redact_secrets(str(exc), token)
        ok = False
        http_status = None

    interval_by_inc: dict[UUID, int] = {
        ni.incident.id: notification_interval_minutes(settings, ni.policy) for ni in send_list
    }

    if ok:
        counts["sla_notify_sent"] += len(send_list)
        for ni in send_list:
            inc = ni.incident
            inc.notification_count = int(inc.notification_count or 0) + 1
            inc.last_notification_at = now
            inc.next_notification_at = now + timedelta(minutes=interval_by_inc[inc.id])
            inc.last_notification_reason = "sent"
            inc.last_error = None
            inc.updated_at = now
            payload = _safe_payload(
                {
                    "mode": "digest" if digest else "single",
                    "digest_size": len(send_list) if digest else 1,
                },
                token,
            )
            await _append_event(
                session,
                incident_id=inc.id,
                status=SlaNotificationEventStatus.SENT.value,
                reason=None,
                telegram_message_id=mid,
                error=None,
                payload_json=payload,
                now=now,
            )
            await _audit(
                session,
                action="sla.notification_sent",
                entity_type="studio_sla_incident",
                entity_id=str(inc.id),
                payload={"telegram_http": http_status, "digest": digest},
            )
        return counts

    counts["sla_notify_failed"] += len(send_list)
    redacted = redact_secrets(err_detail or f"http_{http_status}", token)
    for ni in send_list:
        inc = ni.incident
        inc.last_error = redacted
        inc.last_notification_reason = "failed"
        inc.updated_at = now
        await _append_event(
            session,
            incident_id=inc.id,
            status=SlaNotificationEventStatus.FAILED.value,
            reason=None,
            telegram_message_id=None,
            error=redacted,
            payload_json=_safe_payload({"mode": "digest" if digest else "single"}, token),
            now=now,
        )
        await _audit(
            session,
            action="sla.notification_failed",
            entity_type="studio_sla_incident",
            entity_id=str(inc.id),
            payload={"http_status": http_status, "detail": redacted},
        )
    return counts


async def manual_notify_incident(
    session: AsyncSession,
    settings: Settings,
    incident_id: UUID,
    send_message: SendMessageFn,
    *,
    now: datetime,
) -> dict[str, Any]:
    inc = await session.get(StudioSlaIncident, incident_id)
    if inc is None:
        return {"ok": False, "error": "not_found"}
    chat = await session.get(StudioChat, inc.chat_id)
    if chat is None:
        return {"ok": False, "error": "chat_not_found"}
    policy = await session.scalar(
        select(StudioSlaPolicy).where(
            StudioSlaPolicy.chat_role == inc.chat_role,
            StudioSlaPolicy.is_active.is_(True),
        )
    )
    out = await dispatch_sla_notifications(
        session, settings, [(inc, chat, policy, True)], send_message, now=now
    )
    return {"ok": True, **out}


async def list_notification_events(
    session: AsyncSession,
    *,
    incident_id: UUID | None,
    limit: int,
) -> list[StudioSlaNotificationEvent]:
    lim = min(max(limit, 1), 500)
    stmt = select(StudioSlaNotificationEvent)
    if incident_id is not None:
        stmt = stmt.where(StudioSlaNotificationEvent.incident_id == incident_id)
    stmt = stmt.order_by(StudioSlaNotificationEvent.created_at.desc()).limit(lim)
    return list((await session.scalars(stmt)).all())
