from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import exists, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import get_control_group_chat
from pb_studio.control_group.telegram_outbound import redact_secrets, telegram_send_message
from pb_studio.control_commands.constants import SUMMARY_HELP_TEXT, ControlCommandName, ControlCommandStatus
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.control_commands.parser import parse_control_group_command_line, period_bounds_utc
from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.event_mirror.models import StudioMessage, TelegramRawUpdate
from pb_studio.summaries.constants import SummaryType
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.product import (
    ensure_chat_summary_for_period,
    get_latest_generated_for_chat,
    utc_today_period,
    utc_yesterday_period,
)
from pb_studio.summaries.summary_delivery import deliver_summary_to_control_group_by_id

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sender_is_bot(raw: dict[str, Any]) -> bool:
    from_obj = raw.get("from")
    if not isinstance(from_obj, dict):
        return False
    return bool(from_obj.get("is_bot"))


def _format_summary_reply(summary: StudioChatSummary) -> str:
    return (
        f"Сводка готова (id={summary.id})\n"
        f"Чат: {summary.chat_id}\n"
        f"Период (UTC): {summary.period_start.isoformat()} — {summary.period_end.isoformat()}\n"
        f"Статус: {summary.status}\n"
        f"---\n{(summary.summary_text or '')[:3500]}"
    )


async def _send_text_to_control_group(
    session: AsyncSession,
    settings: Settings,
    text: str,
    *,
    send_message: Any = None,
) -> tuple[bool, int | None, int | None]:
    """sendMessage в активную control group. Возвращает (ok, http_status, telegram_message_id)."""
    send_message = send_message or telegram_send_message
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return False, None, None
    cg = await get_control_group_chat(session)
    if cg is None or cg.chat_role != ChatRole.CONTROL_GROUP.value:
        return False, None, None
    tid = int(cg.telegram_chat_id)
    timeout_s = max(0.5, settings.studio_telegram_send_timeout_ms / 1000.0)
    ok, http_status, err, mid = await send_message(
        bot_token=token,
        chat_id=tid,
        text=text[:4090],
        timeout_seconds=timeout_s,
    )
    if not ok:
        logger.warning("control command reply failed: %s", redact_secrets(err or "", token)[:500])
    return ok, http_status, mid


async def scan_mirror_for_control_commands(
    session: AsyncSession,
    settings: Settings,
    *,
    batch_limit: int | None = None,
) -> dict[str, int]:
    counts = {"scanned": 0, "inserted": 0, "skipped": 0, "skipped_disabled": 0}
    if not settings.studio_control_commands_enabled:
        counts["skipped_disabled"] = 1
        return counts

    cg = await get_control_group_chat(session)
    if cg is None or cg.chat_role != ChatRole.CONTROL_GROUP.value:
        return counts

    lim = min(max(batch_limit or settings.studio_control_commands_max_batch, 1), 200)
    dup_exists = (
        select(StudioControlCommand.id)
        .where(
            StudioControlCommand.control_group_chat_id == cg.id,
            StudioControlCommand.source_message_id == StudioMessage.telegram_message_id,
        )
        .exists()
    )
    stmt = (
        select(StudioMessage)
        .where(
            StudioMessage.chat_id == cg.id,
            StudioMessage.text.isnot(None),
            or_(
                StudioMessage.text.startswith("/summary_today"),
                StudioMessage.text.startswith("/summary_yesterday"),
                StudioMessage.text.startswith("/summary_period"),
                StudioMessage.text.startswith("/summary_latest"),
                StudioMessage.text.startswith("/summary_help"),
                StudioMessage.text.startswith("/summary"),
            ),
            not_(dup_exists),
        )
        .order_by(StudioMessage.date.asc())
        .limit(lim)
    )
    rows = list((await session.scalars(stmt)).all())
    for msg in rows:
        counts["scanned"] += 1
        if _sender_is_bot(msg.raw_message):
            counts["skipped"] += 1
            continue
        parsed = parse_control_group_command_line(msg.text)
        if parsed is None:
            counts["skipped"] += 1
            continue

        src_update_id: int | None = None
        if msg.raw_update_id is not None:
            raw = await session.get(TelegramRawUpdate, msg.raw_update_id)
            if raw is not None:
                src_update_id = int(raw.update_id)
                dup_u = await session.scalar(
                    select(StudioControlCommand.id).where(StudioControlCommand.source_update_id == src_update_id)
                )
                if dup_u is not None:
                    counts["skipped"] += 1
                    continue

        cmd_row = StudioControlCommand(
            source_update_id=src_update_id,
            source_message_id=int(msg.telegram_message_id),
            control_group_chat_id=cg.id,
            command_text=(msg.text or "").strip(),
            command_name=parsed.name,
            args_json=dict(parsed.args),
            status=ControlCommandStatus.PENDING,
        )
        try:
            async with session.begin_nested():
                session.add(cmd_row)
                await session.flush()
            counts["inserted"] += 1
        except IntegrityError:
            counts["skipped"] += 1
            logger.debug("duplicate control command skipped msg_id=%s", msg.telegram_message_id)
    return counts


async def _process_one_command(
    session: AsyncSession,
    cmd: StudioControlCommand,
    settings: Settings,
    *,
    send_message: Any = None,
) -> None:
    meta = {"source": "control_command_7a", "command_id": str(cmd.id)}
    now = utcnow()

    async def reply(txt: str) -> int | None:
        ok, _hs, mid = await _send_text_to_control_group(session, settings, txt, send_message=send_message)
        return mid if ok else None

    try:
        if cmd.command_name == ControlCommandName.SUMMARY_HELP or cmd.command_name == ControlCommandName.UNKNOWN:
            text_out = SUMMARY_HELP_TEXT
            if cmd.command_name == ControlCommandName.UNKNOWN:
                reason = str(cmd.args_json.get("reason") or "")
                if reason:
                    text_out = f"Ошибка: {reason}\n\n" + text_out
            mid = await reply(text_out)
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        target = UUID(str(cmd.args_json["target_chat_id"]))

        if cmd.command_name == ControlCommandName.SUMMARY_TODAY:
            p0, p1 = utc_today_period()
            summary = await ensure_chat_summary_for_period(
                session,
                studio_chat_id=target,
                summary_type=SummaryType.DAILY,
                period_start=p0,
                period_end=p1,
                settings=settings,
                metadata_json=meta,
            )
        elif cmd.command_name == ControlCommandName.SUMMARY_YESTERDAY:
            p0, p1 = utc_yesterday_period()
            summary = await ensure_chat_summary_for_period(
                session,
                studio_chat_id=target,
                summary_type=SummaryType.DAILY,
                period_start=p0,
                period_end=p1,
                settings=settings,
                metadata_json=meta,
            )
        elif cmd.command_name == ControlCommandName.SUMMARY_PERIOD:
            da = str(cmd.args_json.get("date_a") or "")
            db = str(cmd.args_json.get("date_b") or "")
            p0, p1 = period_bounds_utc(da, db)
            summary = await ensure_chat_summary_for_period(
                session,
                studio_chat_id=target,
                summary_type=SummaryType.MANUAL,
                period_start=p0,
                period_end=p1,
                settings=settings,
                metadata_json=meta,
            )
        elif cmd.command_name == ControlCommandName.SUMMARY_LATEST:
            summary = await get_latest_generated_for_chat(session, studio_chat_id=target)
            if summary is None:
                mid = await reply("Нет generated-сводки для этого чата.")
                cmd.status = ControlCommandStatus.PROCESSED
                cmd.processed_at = now
                cmd.response_telegram_message_id = mid
                return
        else:
            cmd.status = ControlCommandStatus.IGNORED
            cmd.processed_at = now
            cmd.last_error = "unsupported command_name"
            return

        cmd.result_summary_id = summary.id

        if settings.studio_summary_delivery_enabled and (settings.telegram_bot_token or "").strip():
            try:
                row2, _reason = await deliver_summary_to_control_group_by_id(
                    session, summary.id, settings, send_message=send_message
                )
                cmd.response_telegram_message_id = row2.telegram_message_id
            except ValueError as exc:
                mid = await reply(_format_summary_reply(summary) + f"\n\n(доставка: {exc})")
                cmd.response_telegram_message_id = mid
        else:
            mid = await reply(_format_summary_reply(summary))
            cmd.response_telegram_message_id = mid

        cmd.status = ControlCommandStatus.PROCESSED
        cmd.processed_at = now
    except Exception as exc:  # noqa: BLE001
        logger.exception("control command failed id=%s", cmd.id)
        cmd.status = ControlCommandStatus.FAILED
        cmd.last_error = str(exc)[:4000]
        cmd.processed_at = now
        try:
            await reply(f"Команда не выполнена: {str(exc)[:500]}")
        except Exception:  # noqa: BLE001
            pass


async def process_pending_control_commands(
    session: AsyncSession,
    settings: Settings,
    *,
    send_message: Any = None,
    batch_limit: int | None = None,
) -> dict[str, int]:
    counts = {
        "examined": 0,
        "processed": 0,
        "failed": 0,
        "skipped_disabled": 0,
    }
    if not settings.studio_control_commands_enabled:
        counts["skipped_disabled"] = 1
        return counts

    lim = min(max(batch_limit or settings.studio_control_commands_max_batch, 1), 200)
    rows = list(
        (
            await session.scalars(
                select(StudioControlCommand)
                .where(StudioControlCommand.status == ControlCommandStatus.PENDING)
                .order_by(StudioControlCommand.created_at.asc())
                .limit(lim)
            )
        ).all()
    )

    for cmd in rows:
        counts["examined"] += 1
        try:
            await _process_one_command(session, cmd, settings, send_message=send_message)
            if cmd.status == ControlCommandStatus.PROCESSED:
                counts["processed"] += 1
            elif cmd.status == ControlCommandStatus.FAILED:
                counts["failed"] += 1
        except Exception:  # noqa: BLE001
            logger.exception("batch item control command id=%s", cmd.id)
            cmd.status = ControlCommandStatus.FAILED
            cmd.last_error = "batch isolation error"
            cmd.processed_at = utcnow()
            counts["failed"] += 1

    return counts


async def run_control_commands_cycle(
    session: AsyncSession,
    settings: Settings,
    *,
    send_message: Any = None,
) -> dict[str, Any]:
    """Один цикл: скан зеркала + обработка pending (идемпотентно по уникальным ключам)."""
    scan = await scan_mirror_for_control_commands(session, settings)
    proc = await process_pending_control_commands(session, settings, send_message=send_message)
    return {"scan": scan, "process": proc}


async def run_control_commands_standalone(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        out = await run_control_commands_cycle(session, settings)
        await session.commit()
    return out


async def list_control_commands(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[StudioControlCommand]:
    lim = min(max(limit, 1), 500)
    stmt = select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()).limit(lim)
    if status:
        stmt = (
            select(StudioControlCommand)
            .where(StudioControlCommand.status == status)
            .order_by(StudioControlCommand.created_at.desc())
            .limit(lim)
        )
    return list((await session.scalars(stmt)).all())
