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
from pb_studio.core.config import Settings
from pb_studio.project_digests.constants import ProjectDigestDeliveryStatus, ProjectDigestStatus
from pb_studio.project_digests.models import StudioProjectDigest
from pb_studio.projects.models import StudioProject

logger = logging.getLogger(__name__)

SendMessageFn = Callable[..., Awaitable[tuple[bool, int | None, str, int | None]]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _failure_status(http_status: int | None, retry_count: int, max_retries: int) -> str:
    if http_status is not None and http_status != 429 and 400 <= http_status < 500:
        return ProjectDigestDeliveryStatus.FAILED_PERMANENT
    if retry_count >= max_retries:
        return ProjectDigestDeliveryStatus.FAILED_PERMANENT
    return ProjectDigestDeliveryStatus.FAILED_RETRYABLE


def format_project_digest_telegram_message(*, digest: StudioProjectDigest, project: StudioProject) -> str:
    title = "📁 Дайджест проекта Studio"
    period = f"Период (UTC): {digest.period_start.isoformat()} — {digest.period_end.isoformat()}"
    head = f"Проект: {project.slug} — {project.name}\nТип: {digest.digest_type} | чатов: {digest.source_chat_count} | сводок: {digest.source_summary_count}"
    body = (digest.digest_text or "").strip() or "(нет текста)"
    return "\n".join([title, "", head, "", period, "", body])


async def try_deliver_project_digest_row(
    session: AsyncSession,
    row: StudioProjectDigest,
    settings: Settings,
    *,
    send_message: SendMessageFn | None = None,
) -> str:
    send_message = send_message or telegram_send_message
    token = (settings.telegram_bot_token or "").strip()
    max_retries = max(1, settings.studio_summary_delivery_max_retries)

    if row.delivery_status == ProjectDigestDeliveryStatus.DELIVERED_TO_CONTROL_GROUP:
        return "skipped_already_delivered"
    if row.status != ProjectDigestStatus.GENERATED:
        return "skipped_not_generated"

    dest_chat = await get_control_group_chat(session)
    if dest_chat is None:
        row.delivery_status = ProjectDigestDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY
        row.delivery_last_error = "no active control group"
        row.updated_at = utcnow()
        return "waiting_no_control_group"

    if dest_chat.chat_role != ChatRole.CONTROL_GROUP.value:
        row.delivery_status = ProjectDigestDeliveryStatus.FAILED_PERMANENT
        row.delivery_last_error = "destination chat is not control_group role"
        row.updated_at = utcnow()
        await _audit(
            session,
            action="project_digests.delivery_blocked",
            entity_type="studio_project_digest",
            entity_id=str(row.id),
            payload={"reason": "destination_not_control_group_role"},
        )
        return "failed_permanent_config"

    proj = await session.get(StudioProject, row.project_id)
    if proj is None:
        row.delivery_status = ProjectDigestDeliveryStatus.FAILED_PERMANENT
        row.delivery_last_error = "project missing"
        row.updated_at = utcnow()
        return "failed_permanent_config"

    dest_tid = int(dest_chat.telegram_chat_id)
    text = format_project_digest_telegram_message(digest=row, project=proj)
    timeout_s = max(0.5, settings.studio_telegram_send_timeout_ms / 1000.0)
    ok, http_status, err, msg_id = await send_message(
        bot_token=token,
        chat_id=dest_tid,
        text=text[:4090],
        timeout_seconds=timeout_s,
    )
    err_redacted = redact_secrets(err or "", token)

    if ok:
        row.delivery_status = ProjectDigestDeliveryStatus.DELIVERED_TO_CONTROL_GROUP
        row.delivered_at = utcnow()
        row.telegram_message_id = msg_id
        row.delivery_last_error = None
        row.updated_at = utcnow()
        cg_row = await get_active_control_group(session)
        await _audit(
            session,
            action="project_digests.delivery_delivered",
            entity_type="studio_project_digest",
            entity_id=str(row.id),
            payload={"destination_telegram_chat_id": dest_tid, "http_status": http_status, "control_group_id": str(cg_row.id) if cg_row else None},
        )
        return "delivered"

    row.delivery_retry_count += 1
    row.delivery_last_error = err_redacted[:4000]
    row.updated_at = utcnow()
    new_status = _failure_status(http_status, row.delivery_retry_count, max_retries)
    row.delivery_status = new_status
    await _audit(
        session,
        action="project_digests.delivery_failed",
        entity_type="studio_project_digest",
        entity_id=str(row.id),
        payload={"http_status": http_status, "retry_count": row.delivery_retry_count},
    )
    return "failed_retryable" if new_status == ProjectDigestDeliveryStatus.FAILED_RETRYABLE else "failed_permanent"


def mark_digest_delivered_from_control_command_reply(
    digest: StudioProjectDigest,
    telegram_message_id: int | None,
) -> None:
    """Ответ команды в control group считается доставкой дайджеста (без второго send)."""
    if telegram_message_id is None:
        return
    now = utcnow()
    digest.delivery_status = ProjectDigestDeliveryStatus.DELIVERED_TO_CONTROL_GROUP
    digest.telegram_message_id = telegram_message_id
    digest.delivered_at = now
    digest.delivery_last_error = None
    digest.updated_at = now


async def deliver_project_digest_by_id(
    session: AsyncSession,
    digest_id: UUID,
    settings: Settings,
    *,
    send_message: SendMessageFn | None = None,
) -> tuple[StudioProjectDigest, str | None]:
    if not (settings.telegram_bot_token or "").strip():
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    row = await session.get(StudioProjectDigest, digest_id)
    if row is None:
        raise ValueError("digest not found")
    if row.status != ProjectDigestStatus.GENERATED:
        raise ValueError("digest must be generated before delivery")
    if row.delivery_status == ProjectDigestDeliveryStatus.DELIVERED_TO_CONTROL_GROUP:
        return row, "already_delivered"

    row.delivery_status = ProjectDigestDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY
    row.updated_at = utcnow()
    await session.flush()
    await try_deliver_project_digest_row(session, row, settings, send_message=send_message)
    return row, None


async def deliver_pending_project_digests_batch(
    session: AsyncSession,
    settings: Settings,
    *,
    send_message: SendMessageFn | None = None,
    batch_limit: int = 50,
) -> dict[str, int]:
    counts = {
        "examined": 0,
        "delivered": 0,
        "failed_retryable": 0,
        "failed_permanent": 0,
        "skipped_no_token": 0,
        "skipped_already_delivered": 0,
        "skipped_not_generated": 0,
        "waiting_no_control_group": 0,
        "failed_permanent_config": 0,
    }
    if not (settings.telegram_bot_token or "").strip():
        counts["skipped_no_token"] = 1
        return counts

    lim = min(max(batch_limit, 1), 200)
    rows = list(
        (
            await session.scalars(
                select(StudioProjectDigest)
                .where(
                    and_(
                        StudioProjectDigest.status == ProjectDigestStatus.GENERATED,
                        StudioProjectDigest.delivery_status.in_(
                            (
                                ProjectDigestDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY,
                                ProjectDigestDeliveryStatus.FAILED_RETRYABLE,
                            )
                        ),
                    )
                )
                .order_by(StudioProjectDigest.created_at.asc())
                .limit(lim)
            )
        ).all()
    )

    for row in rows:
        counts["examined"] += 1
        out = await try_deliver_project_digest_row(session, row, settings, send_message=send_message)
        if out == "delivered":
            counts["delivered"] += 1
        elif out == "skipped_already_delivered":
            counts["skipped_already_delivered"] += 1
        elif out == "skipped_not_generated":
            counts["skipped_not_generated"] += 1
        elif out == "waiting_no_control_group":
            counts["waiting_no_control_group"] += 1
        elif out == "failed_permanent_config":
            counts["failed_permanent_config"] += 1
        elif out == "failed_retryable":
            counts["failed_retryable"] += 1
        elif out == "failed_permanent":
            counts["failed_permanent"] += 1

    return counts
