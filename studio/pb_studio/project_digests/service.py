from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.event_mirror.models import StudioChat
from pb_studio.project_digests.constants import (
    ProjectDigestDeliveryStatus,
    ProjectDigestStatus,
    ProjectDigestType,
)
from pb_studio.project_digests.delivery import deliver_pending_project_digests_batch
from pb_studio.project_digests.models import StudioProjectDigest
from pb_studio.projects.constants import ProjectStatus
from pb_studio.projects.models import StudioProject
from pb_studio.projects.service import list_project_chats
from pb_studio.summaries.constants import SummaryStatus, SummaryType
from pb_studio.summaries.generator import apply_generation_to_row
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.planner import plan_summary_job, utc_day_bounds
from pb_studio.summaries.product import get_latest_generated_for_chat, summaries_clock

logger = logging.getLogger(__name__)

CHAT_SNIPPET_CHARS = 400
EMPTY_ACTIVE_CHATS = "У проекта нет активных чатов."
NO_GENERATED_SUMMARIES = "Нет generated-сводок для активных чатов проекта."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_digest_by_period(
    session: AsyncSession,
    *,
    project_id: UUID,
    digest_type: str,
    period_start: datetime,
    period_end: datetime,
) -> StudioProjectDigest | None:
    return await session.scalar(
        select(StudioProjectDigest).where(
            and_(
                StudioProjectDigest.project_id == project_id,
                StudioProjectDigest.digest_type == digest_type,
                StudioProjectDigest.period_start == period_start,
                StudioProjectDigest.period_end == period_end,
            )
        )
    )


async def list_project_digests(
    session: AsyncSession,
    project_id: UUID,
    *,
    limit: int = 50,
) -> list[StudioProjectDigest]:
    lim = min(max(limit, 1), 200)
    stmt = (
        select(StudioProjectDigest)
        .where(StudioProjectDigest.project_id == project_id)
        .order_by(StudioProjectDigest.created_at.desc())
        .limit(lim)
    )
    return list((await session.scalars(stmt)).all())


async def get_digest(session: AsyncSession, digest_id: UUID) -> StudioProjectDigest | None:
    return await session.get(StudioProjectDigest, digest_id)


async def _ensure_summary_for_digest(
    session: AsyncSession,
    *,
    chat_id: UUID,
    summary_type: str,
    period_start: datetime,
    period_end: datetime,
    settings: Settings,
    meta_extra: dict[str, Any],
) -> tuple[StudioChatSummary | None, dict[str, Any]]:
    """Вернуть generated-сводку или None + запись для metadata (failed и т.д.)."""
    if not settings.studio_summary_generation_enabled:
        raise ValueError("STUDIO_SUMMARY_GENERATION_ENABLED is false")

    meta = {"source": "project_digest_9b", **meta_extra}
    row, _created = await plan_summary_job(
        session,
        studio_chat_id=chat_id,
        summary_type=summary_type,
        period_start=period_start,
        period_end=period_end,
        metadata_json=meta,
    )
    await session.refresh(row)
    if row.status == SummaryStatus.FAILED:
        return None, {
            "chat_id": str(chat_id),
            "summary_id": str(row.id),
            "outcome": "failed_existing",
            "last_error": (row.last_error or "")[:500],
        }
    if row.status == SummaryStatus.GENERATED:
        return row, {"chat_id": str(chat_id), "summary_id": str(row.id), "outcome": "ok"}
    if row.status == SummaryStatus.PENDING:
        try:
            await apply_generation_to_row(session, row, settings)
            await session.refresh(row)
        except Exception as exc:  # noqa: BLE001
            logger.exception("digest chat summary generation failed summary_id=%s", row.id)
            row.status = SummaryStatus.FAILED
            row.last_error = str(exc)[:4000]
            row.updated_at = utcnow()
            await session.flush()
            return None, {
                "chat_id": str(chat_id),
                "summary_id": str(row.id),
                "outcome": "generation_failed",
                "last_error": str(exc)[:500],
            }
    if row.status != SummaryStatus.GENERATED:
        return None, {
            "chat_id": str(chat_id),
            "summary_id": str(row.id),
            "outcome": "not_generated",
            "status": row.status,
        }
    return row, {"chat_id": str(chat_id), "summary_id": str(row.id), "outcome": "ok"}


def _build_digest_body(
    *,
    project: StudioProject,
    digest_type: str,
    period_start: datetime,
    period_end: datetime,
    chat_lines: list[str],
    source_chat_count: int,
    source_summary_count: int,
) -> str:
    lines: list[str] = [
        f"Проект: {project.slug} — {project.name}",
        f"Тип дайджеста: {digest_type}",
        f"Период (UTC): {period_start.isoformat()} — {period_end.isoformat()}",
        f"Активных чатов в проекте: {source_chat_count}",
        f"Учтено сводок (generated): {source_summary_count}",
        "",
        "---",
        "",
    ]
    if not chat_lines:
        lines.append("(нет блоков по чатам)")
    else:
        lines.extend(chat_lines)
    return "\n".join(lines)


async def _finalize_digest_row(
    session: AsyncSession,
    row: StudioProjectDigest,
    *,
    project: StudioProject,
    digest_type: str,
    period_start: datetime,
    period_end: datetime,
    chat_lines: list[str],
    source_chat_count: int,
    source_summary_count: int,
    chat_meta: list[dict[str, Any]],
    extra_meta: dict[str, Any] | None = None,
) -> StudioProjectDigest:
    text = _build_digest_body(
        project=project,
        digest_type=digest_type,
        period_start=period_start,
        period_end=period_end,
        chat_lines=chat_lines,
        source_chat_count=source_chat_count,
        source_summary_count=source_summary_count,
    )
    now = utcnow()
    row.digest_text = text
    row.source_chat_count = source_chat_count
    row.source_summary_count = source_summary_count
    meta: dict[str, Any] = {"chat_summaries": chat_meta}
    if extra_meta:
        meta.update(extra_meta)
    row.metadata_json = meta
    row.status = ProjectDigestStatus.GENERATED
    row.generated_at = now
    row.updated_at = now
    row.last_error = None
    row.delivery_status = ProjectDigestDeliveryStatus.NOT_REQUESTED
    await session.flush()
    return row


async def generate_or_get_project_digest_for_period(
    session: AsyncSession,
    *,
    project_id: UUID,
    digest_type: str,
    period_start: datetime,
    period_end: datetime,
    settings: Settings,
    summary_type_for_chats: str,
) -> tuple[StudioProjectDigest, bool]:
    """
    Идемпотентно: при существующей строке с тем же периодом возвращает её (без пересборки).
    Возвращает (row, created_new_row).
    """
    project = await session.get(StudioProject, project_id)
    if project is None:
        raise ValueError("project not found")
    if project.status != ProjectStatus.ACTIVE.value:
        raise ValueError("project is archived")

    existing = await get_digest_by_period(
        session,
        project_id=project_id,
        digest_type=digest_type,
        period_start=period_start,
        period_end=period_end,
    )
    if existing is not None and existing.status == ProjectDigestStatus.GENERATED:
        return existing, False

    links = await list_project_chats(session, project_id, active_only=True)
    if not links:
        row = StudioProjectDigest(
            project_id=project_id,
            digest_type=digest_type,
            period_start=period_start,
            period_end=period_end,
            status=ProjectDigestStatus.PENDING,
            source_chat_count=0,
            source_summary_count=0,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            got = await get_digest_by_period(
                session,
                project_id=project_id,
                digest_type=digest_type,
                period_start=period_start,
                period_end=period_end,
            )
            assert got is not None
            if got.status == ProjectDigestStatus.GENERATED:
                return got, False
            await _finalize_digest_row(
                session,
                got,
                project=project,
                digest_type=digest_type,
                period_start=period_start,
                period_end=period_end,
                chat_lines=[],
                source_chat_count=0,
                source_summary_count=0,
                chat_meta=[],
            )
            text = EMPTY_ACTIVE_CHATS
            got.digest_text = text
            await session.flush()
            return got, False

        await _finalize_digest_row(
            session,
            row,
            project=project,
            digest_type=digest_type,
            period_start=period_start,
            period_end=period_end,
            chat_lines=[],
            source_chat_count=0,
            source_summary_count=0,
            chat_meta=[],
        )
        row.digest_text = EMPTY_ACTIVE_CHATS
        await session.flush()
        return row, True

    chat_lines: list[str] = []
    chat_meta: list[dict[str, Any]] = []
    ok_summaries = 0
    for link in links:
        ch = await session.get(StudioChat, link.chat_id)
        title = ch.title if ch else None
        ctype = ch.chat_type if ch else "?"
        role = link.role_in_project
        summary, meta = await _ensure_summary_for_digest(
            session,
            chat_id=link.chat_id,
            summary_type=summary_type_for_chats,
            period_start=period_start,
            period_end=period_end,
            settings=settings,
            meta_extra={"project_id": str(project_id), "digest_type": digest_type},
        )
        chat_meta.append(meta)
        if summary is not None:
            ok_summaries += 1
            snip = (summary.summary_text or "")[:CHAT_SNIPPET_CHARS]
            head = f"Чат: {link.chat_id} | роль в проекте: {role} | Studio role: {ch.chat_role if ch else '?'}"
            if title:
                head += f"\nНазвание: {title}"
            head += f"\nТип Telegram: {ctype}"
            chat_lines.append(head + f"\nСводка id={summary.id}\n{snip}\n")
        else:
            head = f"Чат: {link.chat_id} | роль в проекте: {role}"
            chat_lines.append(head + f"\n(сводка недоступна: {meta.get('outcome', '?')})\n")

    row = StudioProjectDigest(
        project_id=project_id,
        digest_type=digest_type,
        period_start=period_start,
        period_end=period_end,
        status=ProjectDigestStatus.PENDING,
        source_chat_count=len(links),
        source_summary_count=0,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        got = await get_digest_by_period(
            session,
            project_id=project_id,
            digest_type=digest_type,
            period_start=period_start,
            period_end=period_end,
        )
        assert got is not None
        if got.status == ProjectDigestStatus.GENERATED:
            return got, False
        await _finalize_digest_row(
            session,
            got,
            project=project,
            digest_type=digest_type,
            period_start=period_start,
            period_end=period_end,
            chat_lines=chat_lines,
            source_chat_count=len(links),
            source_summary_count=ok_summaries,
            chat_meta=chat_meta,
        )
        return got, False

    await _finalize_digest_row(
        session,
        row,
        project=project,
        digest_type=digest_type,
        period_start=period_start,
        period_end=period_end,
        chat_lines=chat_lines,
        source_chat_count=len(links),
        source_summary_count=ok_summaries,
        chat_meta=chat_meta,
    )
    return row, True


def utc_week_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """Понедельник 00:00 UTC … следующий понедельник 00:00 UTC (полуинтервал)."""
    mid = datetime.combine(d, time.min, tzinfo=timezone.utc)
    monday = mid - timedelta(days=mid.weekday())
    nxt = monday + timedelta(days=7)
    return monday, nxt


async def generate_or_get_project_digest_latest(
    session: AsyncSession,
    *,
    project_id: UUID,
    settings: Settings,
) -> tuple[StudioProjectDigest, bool]:
    """Последние generated-сводки по активным чатам; тип weekly + период ISO-недели (UTC) — без коллизий с manual daily."""
    project = await session.get(StudioProject, project_id)
    if project is None:
        raise ValueError("project not found")
    if project.status != ProjectStatus.ACTIVE.value:
        raise ValueError("project is archived")

    d = summaries_clock().date()
    w0, w1 = utc_week_bounds_utc(d)
    dtype = ProjectDigestType.WEEKLY.value

    existing = await get_digest_by_period(
        session,
        project_id=project_id,
        digest_type=dtype,
        period_start=w0,
        period_end=w1,
    )
    if existing is not None and existing.status == ProjectDigestStatus.GENERATED:
        meta = existing.metadata_json or {}
        if meta.get("digest_kind") == "latest_per_chat":
            return existing, False

    links = await list_project_chats(session, project_id, active_only=True)
    if not links:
        return await generate_or_get_project_digest_for_period(
            session,
            project_id=project_id,
            digest_type=dtype,
            period_start=w0,
            period_end=w1,
            settings=settings,
            summary_type_for_chats=SummaryType.DAILY,
        )

    chat_lines: list[str] = []
    chat_meta: list[dict[str, Any]] = []
    summaries_used: list[StudioChatSummary] = []
    for link in links:
        ch = await session.get(StudioChat, link.chat_id)
        title = ch.title if ch else None
        ctype = ch.chat_type if ch else "?"
        role = link.role_in_project
        summary = await get_latest_generated_for_chat(session, studio_chat_id=link.chat_id)
        if summary is None:
            chat_meta.append({"chat_id": str(link.chat_id), "outcome": "no_generated_summary"})
            head = f"Чат: {link.chat_id} | роль в проекте: {role}"
            chat_lines.append(head + "\n(нет generated-сводки)\n")
            continue
        summaries_used.append(summary)
        chat_meta.append(
            {
                "chat_id": str(link.chat_id),
                "summary_id": str(summary.id),
                "outcome": "ok_latest",
                "summary_period_start": summary.period_start.isoformat(),
                "summary_period_end": summary.period_end.isoformat(),
            }
        )
        snip = (summary.summary_text or "")[:CHAT_SNIPPET_CHARS]
        head = f"Чат: {link.chat_id} | роль в проекте: {role} | Studio role: {ch.chat_role if ch else '?'}"
        if title:
            head += f"\nНазвание: {title}"
        head += f"\nТип Telegram: {ctype}"
        chat_lines.append(
            head
            + f"\nПоследняя сводка id={summary.id} период {summary.period_start.isoformat()} — {summary.period_end.isoformat()}\n{snip}\n"
        )

    extra_base: dict[str, Any] = {"digest_kind": "latest_per_chat"}

    if not summaries_used:
        row = StudioProjectDigest(
            project_id=project_id,
            digest_type=dtype,
            period_start=w0,
            period_end=w1,
            status=ProjectDigestStatus.PENDING,
            source_chat_count=len(links),
            source_summary_count=0,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            got = await get_digest_by_period(
                session,
                project_id=project_id,
                digest_type=dtype,
                period_start=w0,
                period_end=w1,
            )
            assert got is not None
            if got.status == ProjectDigestStatus.GENERATED:
                return got, False
            await _finalize_digest_row(
                session,
                got,
                project=project,
                digest_type=dtype,
                period_start=w0,
                period_end=w1,
                chat_lines=chat_lines,
                source_chat_count=len(links),
                source_summary_count=0,
                chat_meta=chat_meta,
                extra_meta={**extra_base, "note": "no_generated_summaries"},
            )
            got.digest_text = NO_GENERATED_SUMMARIES
            await session.flush()
            return got, False

        await _finalize_digest_row(
            session,
            row,
            project=project,
            digest_type=dtype,
            period_start=w0,
            period_end=w1,
            chat_lines=chat_lines,
            source_chat_count=len(links),
            source_summary_count=0,
            chat_meta=chat_meta,
            extra_meta={**extra_base, "note": "no_generated_summaries"},
        )
        row.digest_text = NO_GENERATED_SUMMARIES
        await session.flush()
        return row, True

    agg_start = min(s.period_start for s in summaries_used)
    agg_end = max(s.period_end for s in summaries_used)
    extra_meta = {
        **extra_base,
        "aggregated_summary_period_start": agg_start.isoformat(),
        "aggregated_summary_period_end": agg_end.isoformat(),
    }

    row = StudioProjectDigest(
        project_id=project_id,
        digest_type=dtype,
        period_start=w0,
        period_end=w1,
        status=ProjectDigestStatus.PENDING,
        source_chat_count=len(links),
        source_summary_count=len(summaries_used),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        got = await get_digest_by_period(
            session,
            project_id=project_id,
            digest_type=dtype,
            period_start=w0,
            period_end=w1,
        )
        assert got is not None
        if got.status == ProjectDigestStatus.GENERATED and (got.metadata_json or {}).get("digest_kind") == "latest_per_chat":
            return got, False
        await _finalize_digest_row(
            session,
            got,
            project=project,
            digest_type=dtype,
            period_start=w0,
            period_end=w1,
            chat_lines=chat_lines,
            source_chat_count=len(links),
            source_summary_count=len(summaries_used),
            chat_meta=chat_meta,
            extra_meta=extra_meta,
        )
        return got, False

    await _finalize_digest_row(
        session,
        row,
        project=project,
        digest_type=dtype,
        period_start=w0,
        period_end=w1,
        chat_lines=chat_lines,
        source_chat_count=len(links),
        source_summary_count=len(summaries_used),
        chat_meta=chat_meta,
        extra_meta=extra_meta,
    )
    return row, True


async def generate_daily_project_digests_for_yesterday(
    session: AsyncSession,
    settings: Settings,
    *,
    batch_projects: int = 200,
) -> dict[str, int]:
    """Celery: дайджесты daily за вчера (UTC) для всех active-проектов."""
    counts = {"projects": 0, "digests_created": 0, "digests_reused": 0, "skipped_no_generation": 0, "errors": 0}
    if not settings.studio_summary_generation_enabled:
        counts["skipped_no_generation"] = 1
        return counts

    y = summaries_clock().date() - timedelta(days=1)
    p0, p1 = utc_day_bounds(y)
    lim = min(max(batch_projects, 1), 500)
    projects = list(
        (
            await session.scalars(
                select(StudioProject)
                .where(StudioProject.status == ProjectStatus.ACTIVE.value)
                .order_by(StudioProject.created_at.asc())
                .limit(lim)
            )
        ).all()
    )
    for proj in projects:
        counts["projects"] += 1
        try:
            row, created = await generate_or_get_project_digest_for_period(
                session,
                project_id=proj.id,
                digest_type=ProjectDigestType.DAILY.value,
                period_start=p0,
                period_end=p1,
                settings=settings,
                summary_type_for_chats=SummaryType.DAILY,
            )
            if created:
                counts["digests_created"] += 1
            else:
                counts["digests_reused"] += 1
        except Exception:  # noqa: BLE001
            logger.exception("daily project digest failed project_id=%s", proj.id)
            counts["errors"] += 1
    return counts


async def run_generate_daily_project_digests_standalone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        out = await generate_daily_project_digests_for_yesterday(session, settings)
        await session.commit()
    return out


async def run_deliver_pending_project_digests_standalone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        out = await deliver_pending_project_digests_batch(session, settings)
        await session.commit()
    return out
