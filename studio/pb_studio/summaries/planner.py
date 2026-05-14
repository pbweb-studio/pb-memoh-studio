from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.event_mirror.models import ChatLifecycleEvent, StudioChat, StudioMessage
from pb_studio.summaries.constants import SummaryStatus, SummaryType
from pb_studio.summaries.models import StudioChatSummary

logger = logging.getLogger(__name__)


def utc_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return [period_start, period_end) as UTC datetimes for calendar day."""
    period_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    period_end = period_start + timedelta(days=1)
    return period_start, period_end


async def count_mirror_events_in_period(
    session: AsyncSession,
    *,
    studio_chat_id: UUID,
    period_start: datetime,
    period_end: datetime,
) -> int:
    """Count Event Mirror rows for the chat in [period_start, period_end) (half-open)."""
    msg_q = await session.scalar(
        select(func.count())
        .select_from(StudioMessage)
        .where(
            and_(
                StudioMessage.chat_id == studio_chat_id,
                StudioMessage.date >= period_start,
                StudioMessage.date < period_end,
            )
        )
    )
    life_q = await session.scalar(
        select(func.count())
        .select_from(ChatLifecycleEvent)
        .where(
            and_(
                ChatLifecycleEvent.chat_id == studio_chat_id,
                ChatLifecycleEvent.created_at >= period_start,
                ChatLifecycleEvent.created_at < period_end,
            )
        )
    )
    return int(msg_q or 0) + int(life_q or 0)


async def plan_summary_job(
    session: AsyncSession,
    *,
    studio_chat_id: UUID,
    summary_type: str,
    period_start: datetime,
    period_end: datetime,
    metadata_json: dict[str, Any] | None = None,
) -> tuple[StudioChatSummary, bool]:
    """
    Insert a pending summary job if none exists for (chat, type, period).
    Returns (row, created). No LLM / Memoh / Telegram.
    """
    existing = await session.scalar(
        select(StudioChatSummary).where(
            and_(
                StudioChatSummary.chat_id == studio_chat_id,
                StudioChatSummary.summary_type == summary_type,
                StudioChatSummary.period_start == period_start,
                StudioChatSummary.period_end == period_end,
            )
        )
    )
    if existing is not None:
        return existing, False

    chat = await session.get(StudioChat, studio_chat_id)
    if chat is None:
        raise ValueError(f"studio chat not found: {studio_chat_id}")

    source_event_count = await count_mirror_events_in_period(
        session,
        studio_chat_id=studio_chat_id,
        period_start=period_start,
        period_end=period_end,
    )

    row = StudioChatSummary(
        chat_id=studio_chat_id,
        chat_role=chat.chat_role,
        summary_type=summary_type,
        period_start=period_start,
        period_end=period_end,
        status=SummaryStatus.PENDING,
        source_event_count=source_event_count,
        summary_text=None,
        metadata_json=metadata_json,
    )
    session.add(row)
    await session.flush()
    return row, True


async def plan_daily_chat_summaries(
    session: AsyncSession,
    *,
    reference_utc: datetime | None = None,
) -> dict[str, int]:
    """
    For each mirrored chat, ensure a pending daily job exists for **yesterday** (UTC).
    Does not generate text or call external services.
    """
    reference_utc = reference_utc or datetime.now(timezone.utc)
    day = (reference_utc.astimezone(timezone.utc).date() - timedelta(days=1))
    period_start, period_end = utc_day_bounds(day)

    chats = list((await session.scalars(select(StudioChat))).all())
    created = 0
    skipped = 0
    for chat in chats:
        _, was_created = await plan_summary_job(
            session,
            studio_chat_id=chat.id,
            summary_type=SummaryType.DAILY,
            period_start=period_start,
            period_end=period_end,
            metadata_json={"planned_by": "plan_daily_chat_summaries", "utc_day": day.isoformat()},
        )
        if was_created:
            created += 1
        else:
            skipped += 1

    logger.info(
        "plan_daily_chat_summaries day=%s chats=%s created=%s skipped_duplicates=%s",
        day.isoformat(),
        len(chats),
        created,
        skipped,
    )
    return {
        "chats_examined": len(chats),
        "jobs_created": created,
        "skipped_duplicates": skipped,
        "period_start": int(period_start.timestamp()),
        "period_end": int(period_end.timestamp()),
    }


async def list_summaries(
    session: AsyncSession,
    *,
    limit: int = 100,
    chat_id: UUID | None = None,
) -> list[StudioChatSummary]:
    lim = min(max(limit, 1), 500)
    stmt = select(StudioChatSummary).order_by(StudioChatSummary.created_at.desc()).limit(lim)
    if chat_id is not None:
        stmt = (
            select(StudioChatSummary)
            .where(StudioChatSummary.chat_id == chat_id)
            .order_by(StudioChatSummary.created_at.desc())
            .limit(lim)
        )
    return list((await session.scalars(stmt)).all())


async def get_summary(session: AsyncSession, summary_id: UUID) -> StudioChatSummary | None:
    return await session.get(StudioChatSummary, summary_id)


async def run_plan_daily_standalone() -> dict[str, int]:
    from pb_studio.core.config import get_settings
    from pb_studio.core.database import get_session_factory

    settings = get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        result = await plan_daily_chat_summaries(session)
        await session.commit()
    return result
