from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings
from pb_studio.event_mirror.models import ChatLifecycleEvent, StudioMessage
from pb_studio.summaries.constants import SummaryStatus
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.planner import count_mirror_events_in_period

logger = logging.getLogger(__name__)

EMPTY_PERIOD_TEXT = "За период новых событий нет."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sender_id(raw: dict[str, Any]) -> int | None:
    from_obj = raw.get("from")
    if not isinstance(from_obj, dict):
        return None
    uid = from_obj.get("id")
    return int(uid) if isinstance(uid, int) else None


def _message_body(raw: dict[str, Any]) -> str:
    t = raw.get("text")
    if isinstance(t, str) and t.strip():
        return t.strip()
    c = raw.get("caption")
    if isinstance(c, str) and c.strip():
        return c.strip()
    return ""


def _is_edited(raw: dict[str, Any]) -> bool:
    return raw.get("edit_date") is not None


def build_template_summary_text(
    *,
    chat_title: str | None,
    chat_role: str,
    period_start: datetime,
    period_end: datetime,
    total_event_count: int,
    messages: list[StudioMessage],
    lifecycle_events: list[ChatLifecycleEvent],
    max_bullets: int,
) -> str:
    """Deterministic text from DB facts only (no LLM)."""
    if total_event_count == 0:
        return EMPTY_PERIOD_TEXT

    lines: list[str] = []
    title = chat_title or "(без названия)"
    lines.append(f"Сводка: {title}")
    lines.append(f"Роль чата в Studio: {chat_role}")
    lines.append(
        f"Период (UTC, полуинтервал [start, end)): {period_start.isoformat()} — {period_end.isoformat()}"
    )

    n_msg = len(messages)
    n_life = len(lifecycle_events)
    lines.append(
        f"Всего событий в периоде (по БД): {total_event_count}. "
        f"В шаблон загружено: сообщений — {n_msg}, lifecycle — {n_life}."
    )

    edited = sum(1 for m in messages if _is_edited(m.raw_message))
    plain = n_msg - edited
    lines.append(f"Среди загруженных сообщений: без отметки правки — {plain}, с правкой (edit_date) — {edited}")

    if lifecycle_events:
        ctr = Counter(ev.event_type for ev in lifecycle_events)
        lines.append("События участников (по типу, по загруженным строкам):")
        for et, cnt in sorted(ctr.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"  - {et}: {cnt}")

    senders: Counter[int] = Counter()
    for m in messages:
        sid = _sender_id(m.raw_message)
        if sid is not None:
            senders[sid] += 1
    if senders:
        lines.append("Топ отправителей (по загруженным сообщениям с текстом/caption, user_id):")
        for uid, cnt in senders.most_common(10):
            lines.append(f"  - {uid}: {cnt}")

    bullets: list[str] = []
    for m in messages:
        if len(bullets) >= max_bullets:
            break
        body = _message_body(m.raw_message)
        if not body:
            continue
        one = body.replace("\n", " ").strip()
        if len(one) > 200:
            one = one[:197] + "..."
        mark = "[правка] " if _is_edited(m.raw_message) else ""
        bullets.append(f"  - {mark}msg_id={m.telegram_message_id}: {one}")

    if bullets:
        lines.append("Фрагменты текстовых сообщений (порядок по времени, обрезка по лимитам):")
        lines.extend(bullets)
    elif n_msg:
        lines.append("Среди загруженных сообщений нет непустых text/caption для списка.")

    return "\n".join(lines)


async def _load_messages(
    session: AsyncSession,
    *,
    chat_id: UUID,
    period_start: datetime,
    period_end: datetime,
    limit: int,
) -> list[StudioMessage]:
    lim = max(1, min(limit, 10_000))
    stmt = (
        select(StudioMessage)
        .where(
            and_(
                StudioMessage.chat_id == chat_id,
                StudioMessage.date >= period_start,
                StudioMessage.date < period_end,
            )
        )
        .order_by(StudioMessage.date.asc())
        .limit(lim)
    )
    return list((await session.scalars(stmt)).all())


async def _load_lifecycle(
    session: AsyncSession,
    *,
    chat_id: UUID,
    period_start: datetime,
    period_end: datetime,
    limit: int,
) -> list[ChatLifecycleEvent]:
    lim = max(1, min(limit, 2000))
    stmt = (
        select(ChatLifecycleEvent)
        .where(
            and_(
                ChatLifecycleEvent.chat_id == chat_id,
                ChatLifecycleEvent.created_at >= period_start,
                ChatLifecycleEvent.created_at < period_end,
            )
        )
        .order_by(ChatLifecycleEvent.created_at.asc())
        .limit(lim)
    )
    return list((await session.scalars(stmt)).all())


async def apply_generation_to_row(
    session: AsyncSession,
    row: StudioChatSummary,
    settings: Settings,
) -> None:
    """Fill summary_text for a single pending row; mutates `row` and flushes."""
    from pb_studio.event_mirror.models import StudioChat

    total_count = await count_mirror_events_in_period(
        session,
        studio_chat_id=row.chat_id,
        period_start=row.period_start,
        period_end=row.period_end,
    )

    max_msg = max(1, settings.studio_summary_max_source_messages)
    max_bullets = max(1, settings.studio_summary_max_bullets)

    messages = await _load_messages(
        session,
        chat_id=row.chat_id,
        period_start=row.period_start,
        period_end=row.period_end,
        limit=max_msg,
    )
    lifecycle = await _load_lifecycle(
        session,
        chat_id=row.chat_id,
        period_start=row.period_start,
        period_end=row.period_end,
        limit=max_msg,
    )

    chat = await session.get(StudioChat, row.chat_id)
    chat_title = chat.title if chat else None

    text = build_template_summary_text(
        chat_title=chat_title,
        chat_role=row.chat_role,
        period_start=row.period_start,
        period_end=row.period_end,
        total_event_count=total_count,
        messages=messages,
        lifecycle_events=lifecycle,
        max_bullets=max_bullets,
    )

    meta = dict(row.metadata_json or {})
    meta.update(
        {
            "generator": "template_v1",
            "messages_loaded": len(messages),
            "lifecycle_loaded": len(lifecycle),
            "total_events_in_period": total_count,
            "max_source_messages": max_msg,
            "max_bullets": max_bullets,
        }
    )

    row.summary_text = text
    row.source_event_count = total_count
    row.status = SummaryStatus.GENERATED
    row.generated_at = utcnow()
    row.last_error = None
    row.metadata_json = meta
    row.updated_at = utcnow()
    await session.flush()


async def generate_one_summary(
    session: AsyncSession,
    summary_id: UUID,
    settings: Settings,
) -> tuple[str, str | None]:
    """
    Generate a single summary by id if pending.
    Returns (outcome, detail) where outcome in ok, skipped, failed.
    """
    row = await session.get(StudioChatSummary, summary_id)
    if row is None:
        return "missing", None
    if row.status != SummaryStatus.PENDING:
        return "skipped", row.status
    try:
        await apply_generation_to_row(session, row, settings)
        return "ok", None
    except Exception as exc:  # noqa: BLE001 — изолируем сбой одной строки
        logger.exception("summary generation failed id=%s", summary_id)
        row.status = SummaryStatus.FAILED
        row.last_error = str(exc)[:4000]
        row.updated_at = utcnow()
        await session.flush()
        return "failed", str(exc)


async def generate_pending_summaries_batch(
    session: AsyncSession,
    settings: Settings,
    *,
    batch_limit: int = 50,
) -> dict[str, int]:
    """Process pending rows; errors per row do not abort the batch."""
    counts = {
        "examined": 0,
        "generated": 0,
        "failed": 0,
        "skipped_disabled": 0,
        "skipped_not_pending": 0,
    }
    if not settings.studio_summary_generation_enabled:
        logger.info("summary generation disabled (STUDIO_SUMMARY_GENERATION_ENABLED=false)")
        counts["skipped_disabled"] = 1
        return counts

    lim = min(max(batch_limit, 1), 200)
    rows = list(
        (
            await session.scalars(
                select(StudioChatSummary)
                .where(StudioChatSummary.status == SummaryStatus.PENDING)
                .order_by(StudioChatSummary.created_at.asc())
                .limit(lim)
            )
        ).all()
    )

    for row in rows:
        counts["examined"] += 1
        if row.status != SummaryStatus.PENDING:
            counts["skipped_not_pending"] += 1
            continue
        try:
            await apply_generation_to_row(session, row, settings)
            counts["generated"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("summary batch item failed id=%s", row.id)
            row.status = SummaryStatus.FAILED
            row.last_error = str(exc)[:4000]
            row.updated_at = utcnow()
            counts["failed"] += 1

    return counts


async def run_generate_pending_standalone() -> dict[str, int]:
    from pb_studio.core.config import get_settings
    from pb_studio.core.database import get_session_factory

    settings = get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        result = await generate_pending_summaries_batch(session, settings)
        await session.commit()
    return result
