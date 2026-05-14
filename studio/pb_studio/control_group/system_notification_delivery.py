from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole, SystemNotificationStatus
from pb_studio.control_group.models import StudioSystemNotification
from pb_studio.control_group.service import _audit, get_control_group_chat
from pb_studio.control_group.telegram_outbound import redact_secrets, telegram_send_message
from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory

logger = logging.getLogger(__name__)

SendMessageFn = Callable[..., Awaitable[tuple[bool, int | None, str]]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _failure_status(http_status: int | None, retry_count: int, max_retries: int) -> str:
    if http_status is not None and http_status != 429 and 400 <= http_status < 500:
        return SystemNotificationStatus.FAILED_PERMANENT.value
    if retry_count >= max_retries:
        return SystemNotificationStatus.FAILED_PERMANENT.value
    return SystemNotificationStatus.FAILED_RETRYABLE.value


async def deliver_pending_batch(
    session: AsyncSession,
    *,
    settings: Settings,
    send_message: SendMessageFn | None = None,
    batch_limit: int = 50,
) -> dict[str, int]:
    """Process pending system notifications. Safe to run repeatedly (idempotent per row)."""
    send_message = send_message or telegram_send_message
    counts: dict[str, int] = {
        "examined": 0,
        "delivered": 0,
        "failed_retryable": 0,
        "failed_permanent": 0,
        "skipped": 0,
    }
    if not settings.studio_system_notifications_enabled:
        logger.info("system notification delivery disabled (STUDIO_SYSTEM_NOTIFICATIONS_ENABLED=false)")
        return counts

    token = (settings.telegram_bot_token or "").strip()
    if not token:
        logger.info("system notification delivery skipped: TELEGRAM_BOT_TOKEN not set")
        return counts

    dest_chat = await get_control_group_chat(session)
    if dest_chat is None:
        logger.info("system notification delivery skipped: no active control group")
        return counts

    if dest_chat.chat_role != ChatRole.CONTROL_GROUP.value:
        await _audit(
            session,
            action="control_group.system_notification_delivery_blocked",
            entity_type="studio_chat",
            entity_id=str(dest_chat.id),
            payload={"reason": "destination_not_control_group_role", "role": dest_chat.chat_role},
        )
        counts["skipped"] += 1
        return counts

    dest_tid = int(dest_chat.telegram_chat_id)
    timeout_s = max(0.5, settings.studio_telegram_send_timeout_ms / 1000.0)
    max_retries = max(1, settings.studio_system_notification_max_retries)

    rows = (
        await session.scalars(
            select(StudioSystemNotification)
            .where(
                StudioSystemNotification.status.in_(
                    (
                        SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value,
                        SystemNotificationStatus.FAILED_RETRYABLE.value,
                    )
                )
            )
            .order_by(StudioSystemNotification.created_at.asc())
            .limit(batch_limit)
        )
    ).all()

    for row in rows:
        counts["examined"] += 1
        if row.status not in (
            SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value,
            SystemNotificationStatus.FAILED_RETRYABLE.value,
        ):
            counts["skipped"] += 1
            continue

        if int(row.source_telegram_chat_id) == dest_tid:
            row.retry_count += 1
            row.last_error = "refused: source chat equals control group destination"
            row.status = SystemNotificationStatus.FAILED_PERMANENT.value
            row.updated_at = utcnow()
            counts["failed_permanent"] += 1
            await _audit(
                session,
                action="control_group.system_notification_delivery_refused",
                entity_type="studio_system_notification",
                entity_id=str(row.id),
                payload={"reason": "source_equals_destination"},
            )
            continue

        text = "\n".join(x for x in (row.title or "", row.body or "") if x).strip() or "(system notification)"
        ok, http_status, err = await send_message(
            bot_token=token,
            chat_id=dest_tid,
            text=text,
            timeout_seconds=timeout_s,
        )
        err_redacted = redact_secrets(err, token)

        if ok:
            row.status = SystemNotificationStatus.DELIVERED_TO_CONTROL_GROUP.value
            row.delivered_at = utcnow()
            row.updated_at = utcnow()
            row.last_error = None
            counts["delivered"] += 1
            await _audit(
                session,
                action="control_group.system_notification_delivered",
                entity_type="studio_system_notification",
                entity_id=str(row.id),
                payload={"destination_telegram_chat_id": dest_tid, "http_status": http_status},
            )
            continue

        row.retry_count += 1
        row.last_error = err_redacted[:4000]
        row.updated_at = utcnow()
        new_status = _failure_status(http_status, row.retry_count, max_retries)
        row.status = new_status
        if new_status == SystemNotificationStatus.FAILED_RETRYABLE.value:
            counts["failed_retryable"] += 1
        else:
            counts["failed_permanent"] += 1
        await _audit(
            session,
            action="control_group.system_notification_delivery_failed",
            entity_type="studio_system_notification",
            entity_id=str(row.id),
            payload={
                "http_status": http_status,
                "retry_count": row.retry_count,
                "terminal": new_status == SystemNotificationStatus.FAILED_PERMANENT.value,
            },
        )

    return counts


async def run_deliver_pending_standalone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        result = await deliver_pending_batch(session, settings=settings)
        await session.commit()
    return result


async def list_system_notifications(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[StudioSystemNotification]:
    lim = min(max(limit, 1), 500)
    stmt = select(StudioSystemNotification).order_by(StudioSystemNotification.created_at.desc()).limit(lim)
    if status:
        stmt = (
            select(StudioSystemNotification)
            .where(StudioSystemNotification.status == status)
            .order_by(StudioSystemNotification.created_at.desc())
            .limit(lim)
        )
    return list((await session.scalars(stmt)).all())
