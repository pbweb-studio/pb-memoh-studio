from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import get_control_group_chat
from pb_studio.control_group.telegram_outbound import redact_secrets, telegram_send_message
from pb_studio.control_commands.constants import (
    SUMMARY_AGG_SNIPPET_CHARS,
    SUMMARY_CHATS_MAX_LINES,
    SUMMARY_HELP_TEXT,
    TELEGRAM_TEXT_SAFE_MAX,
    ControlCommandName,
    ControlCommandStatus,
)
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.control_commands.parser import parse_control_group_command_line, period_bounds_utc
from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.event_mirror.models import AuditLog, StudioChat, StudioMessage, TelegramRawUpdate
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

ACCESS_DENIED_REPLY = "Нет прав на команды сводок в этой группе. Обратитесь к администратору."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sender_is_bot(raw: dict[str, Any]) -> bool:
    from_obj = raw.get("from")
    if not isinstance(from_obj, dict):
        return False
    return bool(from_obj.get("is_bot"))


def _sender_telegram_user_id(raw: dict[str, Any]) -> int | None:
    from_obj = raw.get("from")
    if not isinstance(from_obj, dict):
        return None
    uid = from_obj.get("id")
    return int(uid) if isinstance(uid, int) else None


def _acl_allows(settings: Settings, sender_id: int | None) -> bool:
    allowed = settings.studio_control_commands_allowed_user_ids_set
    if not allowed:
        return True
    if sender_id is None:
        return False
    return sender_id in allowed


def _safe_truncate(text: str, max_len: int | None = None) -> str:
    lim = TELEGRAM_TEXT_SAFE_MAX if max_len is None else max_len
    if len(text) <= lim:
        return text
    suffix = "\n\n...(ответ обрезан по лимиту Telegram)"
    cut = max(0, lim - len(suffix))
    return text[:cut] + suffix


def _format_summary_reply(summary: StudioChatSummary) -> str:
    return (
        f"Сводка готова (id={summary.id})\n"
        f"Чат: {summary.chat_id}\n"
        f"Период (UTC): {summary.period_start.isoformat()} — {summary.period_end.isoformat()}\n"
        f"Статус: {summary.status}\n"
        f"---\n{(summary.summary_text or '')[:3500]}"
    )


async def _audit_control_command(
    session: AsyncSession,
    *,
    action: str,
    command_id: UUID,
    command_name: str,
    payload: dict[str, Any],
) -> None:
    session.add(
        AuditLog(
            action=action,
            entity_type="studio_control_command",
            entity_id=str(command_id),
            payload={"command_name": command_name, **payload},
        )
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


async def _list_mirror_chats_excluding_control_group(
    session: AsyncSession,
    *,
    exclude_chat_id: UUID,
) -> list[StudioChat]:
    stmt = (
        select(StudioChat)
        .where(StudioChat.id != exclude_chat_id)
        .order_by(StudioChat.created_at.asc())
    )
    return list((await session.scalars(stmt)).all())


def _format_chat_line(chat: StudioChat) -> str:
    title = (chat.title or "").strip() or "-"
    return (
        f"{chat.id} | tg={chat.telegram_chat_id} | role={chat.chat_role} | "
        f"type={chat.chat_type} | title={title}"
    )


def _build_summary_chats_text(chats: list[StudioChat]) -> str:
    if not chats:
        return "Нет зеркалируемых чатов (кроме control group)."
    lines = ["Чаты Studio (кроме активной control group):", ""]
    total = len(chats)
    shown = chats[:SUMMARY_CHATS_MAX_LINES]
    for c in shown:
        lines.append(_format_chat_line(c))
    if total > len(shown):
        lines.append("")
        lines.append(f"... и ещё {total - len(shown)} чат(ов); список обрезан.")
    return _safe_truncate("\n".join(lines))


def _parse_sender_id(args: dict[str, Any]) -> int | None:
    raw = args.get("sender_telegram_user_id")
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


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
                StudioMessage.text.startswith("/summary_chats"),
                StudioMessage.text.startswith("/summary_all_today"),
                StudioMessage.text.startswith("/summary_all_yesterday"),
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
            raw_upd = await session.get(TelegramRawUpdate, msg.raw_update_id)
            if raw_upd is not None:
                src_update_id = int(raw_upd.update_id)
                dup_u = await session.scalar(
                    select(StudioControlCommand.id).where(StudioControlCommand.source_update_id == src_update_id)
                )
                if dup_u is not None:
                    counts["skipped"] += 1
                    continue

        args: dict[str, Any] = dict(parsed.args)
        sid = _sender_telegram_user_id(msg.raw_message)
        if sid is not None:
            args["sender_telegram_user_id"] = sid

        cmd_row = StudioControlCommand(
            source_update_id=src_update_id,
            source_message_id=int(msg.telegram_message_id),
            control_group_chat_id=cg.id,
            command_text=(msg.text or "").strip(),
            command_name=parsed.name,
            args_json=args,
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
    meta = {"source": "control_command_7b", "command_id": str(cmd.id)}
    now = utcnow()

    async def reply(txt: str) -> int | None:
        ok, _hs, mid = await _send_text_to_control_group(session, settings, txt, send_message=send_message)
        return mid if ok else None

    sender_id = _parse_sender_id(cmd.args_json)
    if not _acl_allows(settings, sender_id):
        mid = await reply(ACCESS_DENIED_REPLY)
        cmd.status = ControlCommandStatus.FAILED_ACCESS_DENIED
        cmd.processed_at = now
        cmd.response_telegram_message_id = mid
        cmd.last_error = "access_denied"
        await _audit_control_command(
            session,
            action="control_commands.access_denied",
            command_id=cmd.id,
            command_name=cmd.command_name,
            payload={"sender_telegram_user_id": sender_id},
        )
        return

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

        cg = await get_control_group_chat(session)
        if cg is None:
            cmd.status = ControlCommandStatus.FAILED
            cmd.last_error = "control group not configured"
            cmd.processed_at = now
            await reply("Управляющая группа не настроена.")
            return

        if cmd.command_name == ControlCommandName.SUMMARY_CHATS:
            others = await _list_mirror_chats_excluding_control_group(session, exclude_chat_id=cg.id)
            body = _build_summary_chats_text(others)
            mid = await reply(body)
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name in (ControlCommandName.SUMMARY_ALL_TODAY, ControlCommandName.SUMMARY_ALL_YESTERDAY):
            if cmd.command_name == ControlCommandName.SUMMARY_ALL_TODAY:
                p0, p1 = utc_today_period()
                label = "сегодня"
            else:
                p0, p1 = utc_yesterday_period()
                label = "вчера"
            chats = await _list_mirror_chats_excluding_control_group(session, exclude_chat_id=cg.id)
            header = f"Сводки ({label}, UTC): {p0.isoformat()} — {p1.isoformat()}\nЧатов: {len(chats)}\n"
            blocks: list[str] = []
            for ch in chats:
                block_head = f"\n---\n{ch.id} | tg={ch.telegram_chat_id} | role={ch.chat_role}\n"
                try:
                    summary = await ensure_chat_summary_for_period(
                        session,
                        studio_chat_id=ch.id,
                        summary_type=SummaryType.DAILY,
                        period_start=p0,
                        period_end=p1,
                        settings=settings,
                        metadata_json=meta,
                    )
                    snip = (summary.summary_text or "")[:SUMMARY_AGG_SNIPPET_CHARS]
                    blocks.append(block_head + f"summary_id={summary.id} status={summary.status}\n{snip}")
                except Exception as exc:  # noqa: BLE001
                    err_short = str(exc)[:200]
                    blocks.append(block_head + f"ошибка: {err_short}")
            body = _safe_truncate(header + "".join(blocks))
            mid = await reply(body)
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name not in {
            ControlCommandName.SUMMARY_TODAY,
            ControlCommandName.SUMMARY_YESTERDAY,
            ControlCommandName.SUMMARY_PERIOD,
            ControlCommandName.SUMMARY_LATEST,
        }:
            cmd.status = ControlCommandStatus.IGNORED
            cmd.processed_at = now
            cmd.last_error = "unsupported command_name"
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
        token = (settings.telegram_bot_token or "").strip()
        safe_err = redact_secrets(str(exc), token)[:4000]
        cmd.status = ControlCommandStatus.FAILED
        cmd.last_error = safe_err
        cmd.processed_at = now
        try:
            await reply(f"Команда не выполнена: {redact_secrets(str(exc)[:500], token)}")
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
        "access_denied": 0,
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
            elif cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED:
                counts["access_denied"] += 1
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
    command_name: str | None = None,
    limit: int = 100,
) -> list[StudioControlCommand]:
    lim = min(max(limit, 1), 500)
    conds = []
    if status:
        conds.append(StudioControlCommand.status == status)
    if command_name:
        conds.append(StudioControlCommand.command_name == command_name)
    stmt = select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()).limit(lim)
    if conds:
        stmt = (
            select(StudioControlCommand)
            .where(and_(*conds))
            .order_by(StudioControlCommand.created_at.desc())
            .limit(lim)
        )
    return list((await session.scalars(stmt)).all())
