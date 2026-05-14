from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings
from pb_studio.event_mirror.models import ChatLifecycleEvent, StudioChat, StudioMessage, StudioTelegramUser
from pb_studio.history_import.constants import (
    HistoryImportJobStatus,
    HistoryImportSourceType,
)
from pb_studio.history_import.models import StudioHistoryImportJob
from pb_studio.history_import import parser


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_chat(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    title: str | None,
    export_chat_type: str | None,
    now: datetime,
) -> StudioChat:
    row = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == telegram_chat_id))
    api_type = parser._map_chat_type_to_api(export_chat_type)
    extra: dict[str, Any] = {"studio_history_import": True}
    if row is None:
        row = StudioChat(
            telegram_chat_id=telegram_chat_id,
            chat_type=api_type,
            title=title,
            username=None,
            extra=extra,
            chat_role="unknown",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row
    row.chat_type = api_type
    if title is not None:
        row.title = title
    merged = dict(row.extra or {})
    merged.update(extra)
    row.extra = merged
    row.updated_at = now
    await session.flush()
    return row


async def _ensure_user(session: AsyncSession, user: dict[str, Any], *, now: datetime) -> None:
    uid = int(user["id"])
    row = await session.scalar(select(StudioTelegramUser).where(StudioTelegramUser.telegram_user_id == uid))
    if row is None:
        session.add(
            StudioTelegramUser(
                telegram_user_id=uid,
                username=user.get("username"),
                first_name=user.get("first_name"),
                last_name=user.get("last_name"),
                is_bot=bool(user.get("is_bot", False)),
                created_at=now,
                updated_at=now,
            )
        )
    else:
        row.username = user.get("username", row.username)
        row.first_name = user.get("first_name", row.first_name)
        row.last_name = user.get("last_name", row.last_name)
        row.is_bot = bool(user.get("is_bot", row.is_bot))
        row.updated_at = now
    await session.flush()


async def _message_exists(session: AsyncSession, *, chat_id: UUID, telegram_message_id: int) -> bool:
    q = await session.scalar(
        select(StudioMessage.id).where(
            StudioMessage.chat_id == chat_id,
            StudioMessage.telegram_message_id == telegram_message_id,
        )
    )
    return q is not None


async def run_telegram_desktop_json_import(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_bytes: bytes,
    file_name: str | None,
) -> StudioHistoryImportJob:
    """
    Синхронный импорт: создаёт job, пишет studio_chats / studio_messages / lifecycle.
    Без Memoh, без TelegramRawUpdate (raw_update_id = null).
    """
    now = utcnow()
    job = StudioHistoryImportJob(
        source_type=HistoryImportSourceType.TELEGRAM_DESKTOP_JSON,
        status=HistoryImportJobStatus.PROCESSING,
        file_name=(file_name or "").strip() or None,
        imported_chat_count=0,
        imported_message_count=0,
        skipped_count=0,
        created_at=now,
        started_at=now,
        metadata_json={"byte_length": len(raw_bytes)},
    )
    session.add(job)
    await session.flush()

    try:
        root = parser.load_telegram_desktop_json(raw_bytes)
        chat_dicts = parser.iter_export_chat_dicts(root)
    except ValueError as exc:
        job.status = HistoryImportJobStatus.FAILED
        job.last_error = str(exc)[:4000]
        job.completed_at = utcnow()
        await session.flush()
        return job

    imported_chats = 0
    imported_messages = 0
    skipped = 0

    for chat_export in chat_dicts:
        cid = chat_export.get("id")
        if cid is None:
            skipped += 1
            continue
        try:
            telegram_chat_id = int(cid)
        except (TypeError, ValueError):
            skipped += 1
            continue

        chat_name = chat_export.get("name") if isinstance(chat_export.get("name"), str) else None
        if chat_name is None and isinstance(chat_export.get("title"), str):
            chat_name = chat_export.get("title")
        export_type = chat_export.get("type")
        export_type_s = str(export_type) if export_type is not None else None

        chat_row = await _ensure_chat(
            session,
            telegram_chat_id=telegram_chat_id,
            title=chat_name,
            export_chat_type=export_type_s,
            now=now,
        )
        imported_chats += 1

        for kind, payload in parser.iter_chat_messages(
            chat_export,
            telegram_chat_id=telegram_chat_id,
            chat_name=chat_name,
            export_chat_type=export_type_s,
        ):
            if kind == "skip" or payload is None:
                skipped += 1
                continue
            if kind == "service":
                assert isinstance(payload, parser.NormalizedServiceEvent)
                session.add(
                    ChatLifecycleEvent(
                        chat_id=chat_row.id,
                        raw_update_id=None,
                        event_type=payload.event_type,
                        actor_telegram_user_id=payload.actor_telegram_user_id,
                        actor_is_bot=payload.actor_is_bot,
                        raw_fragment=payload.raw_fragment,
                        created_at=payload.date,
                    )
                )
                await session.flush()
                continue

            assert isinstance(payload, parser.NormalizedMessage)
            if "from" in payload.raw_bot_shaped:
                await _ensure_user(session, payload.raw_bot_shaped["from"], now=now)

            exists = await _message_exists(
                session, chat_id=chat_row.id, telegram_message_id=payload.telegram_message_id
            )
            if exists:
                continue

            session.add(
                StudioMessage(
                    chat_id=chat_row.id,
                    raw_update_id=None,
                    telegram_message_id=payload.telegram_message_id,
                    date=payload.date,
                    text=payload.text,
                    caption=payload.caption,
                    raw_message=dict(payload.raw_bot_shaped),
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            imported_messages += 1

    job.imported_chat_count = imported_chats
    job.imported_message_count = imported_messages
    job.skipped_count = skipped
    job.status = HistoryImportJobStatus.COMPLETED
    job.completed_at = utcnow()
    job.metadata_json = {
        "byte_length": len(raw_bytes),
        "export_chat_roots": len(chat_dicts),
    }
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: UUID) -> StudioHistoryImportJob | None:
    return await session.get(StudioHistoryImportJob, job_id)


async def list_jobs(session: AsyncSession, *, limit: int = 50) -> list[StudioHistoryImportJob]:
    lim = min(max(limit, 1), 200)
    q = select(StudioHistoryImportJob).order_by(StudioHistoryImportJob.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())
