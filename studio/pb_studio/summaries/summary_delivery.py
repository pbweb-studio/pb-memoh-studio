from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import _audit, get_active_control_group, get_control_group_chat
from pb_studio.control_group.telegram_outbound import redact_secrets, telegram_send_message
from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.event_mirror.models import StudioChat
from pb_studio.summaries.constants import SummaryDeliveryStatus, SummaryStatus
from pb_studio.summaries.models import StudioChatSummary

logger = logging.getLogger(__name__)

SendMessageFn = Callable[..., Awaitable[tuple[bool, int | None, str, int | None]]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _failure_status(http_status: int | None, retry_count: int, max_retries: int) -> str:
    if http_status is not None and http_status != 429 and 400 <= http_status < 500:
        return SummaryDeliveryStatus.FAILED_PERMANENT
    if retry_count >= max_retries:
        return SummaryDeliveryStatus.FAILED_PERMANENT
    return SummaryDeliveryStatus.FAILED_RETRYABLE


def format_summary_delivery_message(*, row: StudioChatSummary, source_chat: StudioChat | None) -> str:
    title = "📊 Сводка Studio"
    period = f"Период (UTC): {row.period_start.isoformat()} — {row.period_end.isoformat()}"
    role_line = f"Роль исходного чата: {row.chat_role}"
    if source_chat and source_chat.title:
        role_line += f" ({source_chat.title})"
    body = (row.summary_text or "").strip() or "(нет текста сводки)"
    parts = [title, "", period, role_line, "", body]
    return "\n".join(parts)


async def try_deliver_summary_row(
    session: AsyncSession,
    row: StudioChatSummary,
    settings: Settings,
    *,
    send_message: SendMessageFn | None = None,
) -> str:
    """
    Attempt Telegram delivery for one row; mutates row. Caller commits.
    Returns a short outcome token for metrics (not an HTTP status).
    """
    send_message = send_message or telegram_send_message
    token = (settings.telegram_bot_token or "").strip()
    max_retries = max(1, settings.studio_summary_delivery_max_retries)

    if row.delivery_status == SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP:
        return "skipped_already_delivered"
    if row.status != SummaryStatus.GENERATED:
        return "skipped_not_generated"

    dest_chat = await get_control_group_chat(session)
    if dest_chat is None:
        row.delivery_status = SummaryDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY
        row.delivery_last_error = "no active control group"
        row.updated_at = utcnow()
        return "waiting_no_control_group"

    if dest_chat.chat_role != ChatRole.CONTROL_GROUP.value:
        row.delivery_status = SummaryDeliveryStatus.FAILED_PERMANENT
        row.delivery_last_error = "destination chat is not control_group role"
        row.updated_at = utcnow()
        await _audit(
            session,
            action="summaries.delivery_blocked",
            entity_type="studio_chat_summary",
            entity_id=str(row.id),
            payload={"reason": "destination_not_control_group_role", "role": dest_chat.chat_role},
        )
        return "failed_permanent_config"

    source_chat = await session.get(StudioChat, row.chat_id)
    if source_chat is None:
        row.delivery_status = SummaryDeliveryStatus.FAILED_PERMANENT
        row.delivery_last_error = "source studio chat missing"
        row.updated_at = utcnow()
        return "failed_permanent_config"

    dest_tid = int(dest_chat.telegram_chat_id)
    if int(source_chat.telegram_chat_id) == dest_tid:
        row.delivery_last_error = "refused: summarized chat equals control group destination"
        row.delivery_status = SummaryDeliveryStatus.FAILED_PERMANENT
        row.updated_at = utcnow()
        await _audit(
            session,
            action="summaries.delivery_refused",
            entity_type="studio_chat_summary",
            entity_id=str(row.id),
            payload={"reason": "source_equals_destination"},
        )
        return "refused_source_equals_dest"

    cg_row = await get_active_control_group(session)
    text = format_summary_delivery_message(row=row, source_chat=source_chat)
    timeout_s = max(0.5, settings.studio_telegram_send_timeout_ms / 1000.0)
    ok, http_status, err, msg_id = await send_message(
        bot_token=token,
        chat_id=dest_tid,
        text=text,
        timeout_seconds=timeout_s,
    )
    err_redacted = redact_secrets(err, token)

    if ok:
        row.delivery_status = SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP
        row.delivered_at = utcnow()
        row.telegram_message_id = msg_id
        row.destination_control_group_id = cg_row.id if cg_row else None
        row.delivery_last_error = None
        row.updated_at = utcnow()
        await _audit(
            session,
            action="summaries.delivery_delivered",
            entity_type="studio_chat_summary",
            entity_id=str(row.id),
            payload={"destination_telegram_chat_id": dest_tid, "http_status": http_status},
        )
        return "delivered"

    row.delivery_retry_count += 1
    row.delivery_last_error = err_redacted[:4000]
    row.updated_at = utcnow()
    new_status = _failure_status(http_status, row.delivery_retry_count, max_retries)
    row.delivery_status = new_status
    await _audit(
        session,
        action="summaries.delivery_failed",
        entity_type="studio_chat_summary",
        entity_id=str(row.id),
        payload={
            "http_status": http_status,
            "delivery_retry_count": row.delivery_retry_count,
            "terminal": new_status == SummaryDeliveryStatus.FAILED_PERMANENT,
        },
    )
    if new_status == SummaryDeliveryStatus.FAILED_RETRYABLE:
        return "failed_retryable"
    return "failed_permanent"


async def deliver_summary_to_control_group_by_id(
    session: AsyncSession,
    summary_id: UUID,
    settings: Settings,
    *,
    send_message: SendMessageFn | None = None,
) -> tuple[StudioChatSummary, str | None]:
    if not settings.studio_summary_delivery_enabled:
        raise ValueError("STUDIO_SUMMARY_DELIVERY_ENABLED is false")
    if not (settings.telegram_bot_token or "").strip():
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    row = await session.get(StudioChatSummary, summary_id)
    if row is None:
        raise ValueError("summary not found")
    if row.status != SummaryStatus.GENERATED:
        raise ValueError("summary must be generated before delivery")
    if row.delivery_status == SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP:
        return row, "already_delivered"

    row.delivery_status = SummaryDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY
    row.updated_at = utcnow()
    await session.flush()
    await try_deliver_summary_row(session, row, settings, send_message=send_message)
    return row, None


async def deliver_pending_summaries_batch(
    session: AsyncSession,
    settings: Settings,
    *,
    send_message: SendMessageFn | None = None,
    batch_limit: int = 50,
) -> dict[str, int]:
    counts: dict[str, int] = {
        "examined": 0,
        "delivered": 0,
        "failed_retryable": 0,
        "failed_permanent": 0,
        "skipped_disabled": 0,
        "skipped_no_token": 0,
        "waiting_no_control_group": 0,
        "skipped_already_delivered": 0,
        "skipped_not_generated": 0,
        "failed_permanent_config": 0,
        "refused_source_equals_dest": 0,
    }
    if not settings.studio_summary_delivery_enabled:
        logger.info("summary delivery disabled (STUDIO_SUMMARY_DELIVERY_ENABLED=false)")
        counts["skipped_disabled"] = 1
        return counts

    if not (settings.telegram_bot_token or "").strip():
        logger.info("summary delivery skipped: TELEGRAM_BOT_TOKEN not set")
        counts["skipped_no_token"] = 1
        return counts

    lim = min(max(batch_limit, 1), 200)
    rows = list(
        (
            await session.scalars(
                select(StudioChatSummary)
                .where(
                    and_(
                        StudioChatSummary.status == SummaryStatus.GENERATED,
                        StudioChatSummary.delivery_status.in_(
                            (
                                SummaryDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY,
                                SummaryDeliveryStatus.FAILED_RETRYABLE,
                            )
                        ),
                    )
                )
                .order_by(StudioChatSummary.created_at.asc())
                .limit(lim)
            )
        ).all()
    )

    for row in rows:
        counts["examined"] += 1
        outcome = await try_deliver_summary_row(session, row, settings, send_message=send_message)
        if outcome == "delivered":
            counts["delivered"] += 1
        elif outcome == "failed_retryable":
            counts["failed_retryable"] += 1
        elif outcome == "failed_permanent":
            counts["failed_permanent"] += 1
        elif outcome == "failed_permanent_config":
            counts["failed_permanent_config"] += 1
        elif outcome == "waiting_no_control_group":
            counts["waiting_no_control_group"] += 1
        elif outcome == "skipped_already_delivered":
            counts["skipped_already_delivered"] += 1
        elif outcome == "skipped_not_generated":
            counts["skipped_not_generated"] += 1
        elif outcome == "refused_source_equals_dest":
            counts["refused_source_equals_dest"] += 1

    return counts


async def run_deliver_summaries_standalone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        result = await deliver_pending_summaries_batch(session, settings=settings)
        await session.commit()
    return result
