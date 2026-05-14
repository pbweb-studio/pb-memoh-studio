from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings
from pb_studio.event_mirror.models import StudioChat
from pb_studio.summaries.constants import SummaryStatus
from pb_studio.summaries.generator import apply_generation_to_row
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.planner import plan_summary_job, utc_day_bounds


def summaries_clock() -> datetime:
    """UTC «сейчас» для today/yesterday; в тестах можно monkeypatch."""
    return datetime.now(timezone.utc)


async def ensure_chat_summary_for_period(
    session: AsyncSession,
    *,
    studio_chat_id: UUID,
    summary_type: str,
    period_start: datetime,
    period_end: datetime,
    settings: Settings,
) -> StudioChatSummary:
    """
    Вернуть generated-сводку за период: существующая generated, иначе pending→generate, иначе plan+generate.
    Только Studio DB. Требует STUDIO_SUMMARY_GENERATION_ENABLED=true.
    """
    if not settings.studio_summary_generation_enabled:
        raise ValueError("STUDIO_SUMMARY_GENERATION_ENABLED is false — включите для этого API")

    chat = await session.get(StudioChat, studio_chat_id)
    if chat is None:
        raise ValueError("studio chat not found")

    row, _created = await plan_summary_job(
        session,
        studio_chat_id=studio_chat_id,
        summary_type=summary_type,
        period_start=period_start,
        period_end=period_end,
        metadata_json={"source": "product_api_6c"},
    )

    if row.status == SummaryStatus.FAILED:
        raise ValueError("summary for this period exists with status failed — исправьте в БД перед повтором")

    if row.status == SummaryStatus.GENERATED:
        return row

    await apply_generation_to_row(session, row, settings)
    await session.refresh(row)
    return row


async def get_latest_generated_for_chat(
    session: AsyncSession,
    *,
    studio_chat_id: UUID,
) -> StudioChatSummary | None:
    stmt = (
        select(StudioChatSummary)
        .where(
            and_(
                StudioChatSummary.chat_id == studio_chat_id,
                StudioChatSummary.status == SummaryStatus.GENERATED,
            )
        )
        .order_by(func.coalesce(StudioChatSummary.generated_at, StudioChatSummary.created_at).desc())
        .limit(1)
    )
    return await session.scalar(stmt)


def utc_today_period() -> tuple[datetime, datetime]:
    d = summaries_clock().date()
    return utc_day_bounds(d)


def utc_yesterday_period() -> tuple[datetime, datetime]:
    d = summaries_clock().date() - timedelta(days=1)
    return utc_day_bounds(d)
