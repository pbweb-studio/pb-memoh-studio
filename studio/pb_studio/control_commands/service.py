from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import get_control_group_chat
from pb_studio.control_group.telegram_outbound import redact_secrets, telegram_send_message
from pb_studio.control_commands.constants import (
    KB_HELP_TEXT,
    PROJECT_HELP_TEXT,
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
from pb_studio.knowledge import service as studio_kb_service
from pb_studio.knowledge.embeddings import redact_embedding_error
from pb_studio.knowledge.rag import ask_knowledge_base
from pb_studio.knowledge.constants import KnowledgeVersionStatus
from pb_studio.knowledge.models import StudioKnowledgeDocumentVersion
from pb_studio.project_digests import service as project_digests_svc
from pb_studio.project_digests.constants import ProjectDigestType
from pb_studio.project_digests.delivery import mark_digest_delivered_from_control_command_reply
from pb_studio.projects import service as studio_projects_service
from pb_studio.projects.constants import ProjectStatus, RoleInProject
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
                StudioMessage.text.startswith("/project"),
                StudioMessage.text.startswith("/kb"),
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
        raw_cmd = (cmd.command_text or "").strip()
        if raw_cmd.startswith("/kb"):
            await _dispatch_kb_control_commands(session, cmd, settings, reply, now)
            return
        if raw_cmd.startswith("/project_digest"):
            await _dispatch_project_digest_control_commands(session, cmd, settings, reply, now)
            return
        if raw_cmd.startswith("/project"):
            await _dispatch_project_control_commands(session, cmd, settings, reply, now)
            return

        if cmd.command_name == ControlCommandName.SUMMARY_HELP or (
            cmd.command_name == ControlCommandName.UNKNOWN
            and not raw_cmd.startswith("/project")
            and not raw_cmd.startswith("/kb")
        ):
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


async def _kb_resolve_active_version(
    session: AsyncSession, doc_id: UUID, doc_metadata: dict[str, Any] | None
) -> StudioKnowledgeDocumentVersion | None:
    meta = doc_metadata or {}
    aid = meta.get("active_version_id")
    if aid:
        try:
            vid = UUID(str(aid))
        except ValueError:
            vid = None
        if vid is not None:
            v = await session.get(StudioKnowledgeDocumentVersion, vid)
            if v is not None and v.document_id == doc_id and v.status == KnowledgeVersionStatus.PARSED:
                return v
    versions = await studio_kb_service.list_versions(session, doc_id)
    parsed = [x for x in versions if x.status == KnowledgeVersionStatus.PARSED]
    if not parsed:
        return None
    return max(parsed, key=lambda x: x.version_number)


def _redact_kb_error_message(message: str, settings: Settings, telegram_token: str | None) -> str:
    chat_key = (settings.studio_kb_chat_api_key or "").strip() or None
    out = redact_embedding_error(message, chat_key)
    return redact_secrets(out, telegram_token or None)


async def _dispatch_kb_control_commands(
    session: AsyncSession,
    cmd: StudioControlCommand,
    settings: Settings,
    reply,
    now: datetime,
) -> None:
    token = (settings.telegram_bot_token or "").strip()
    try:
        if not settings.studio_kb_enabled:
            mid = await reply("База знаний выключена (STUDIO_KB_ENABLED=false).")
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.UNKNOWN:
            reason = str(cmd.args_json.get("reason") or "")
            text_out = KB_HELP_TEXT
            if reason:
                text_out = f"Ошибка: {reason}\n\n" + text_out
            mid = await reply(text_out)
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.KB_HELP:
            mid = await reply(KB_HELP_TEXT)
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            await _audit_control_command(
                session,
                action="control_commands.kb_help",
                command_id=cmd.id,
                command_name=cmd.command_name,
                payload={},
            )
            return

        if cmd.command_name == ControlCommandName.KB_LIST:
            rows = await studio_kb_service.list_documents(session, limit=40)
            lines = ["Документы KB:"]
            for d in rows:
                lines.append(f"- {d.title} | id={d.id} | status={d.status}")
            if not rows:
                lines.append("(пусто)")
            mid = await reply(_safe_truncate("\n".join(lines)))
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.KB_GET:
            did = UUID(str(cmd.args_json.get("document_id") or ""))
            doc = await studio_kb_service.get_document(session, did)
            if doc is None:
                mid = await reply("Документ не найден.")
            else:
                av = await _kb_resolve_active_version(session, doc.id, doc.metadata_json)
                chs = await studio_kb_service.list_chunks(session, av.id) if av is not None else []
                chunk_n = len(chs)
                snip = (chs[0].content_text or "")[:600] if chs else ""
                mid = await reply(
                    _safe_truncate(
                        f"Документ: {doc.title}\n"
                        f"id={doc.id}\nstatus={doc.status}\nproject_id={doc.project_id}\n"
                        f"active_version={av.id if av else '—'} chunks={chunk_n}\n---\n{snip}"
                    )
                )
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.KB_PARSE:
            did = UUID(str(cmd.args_json.get("document_id") or ""))
            try:
                out = await studio_kb_service.parse_all_pending_versions_for_document(session, did, settings)
                mid = await reply(f"KB parse: parsed={out['parsed']} failed={out['failed']}")
            except ValueError as exc:
                mid = await reply(f"Ошибка: {exc}")
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            await _audit_control_command(
                session,
                action="control_commands.kb_parse",
                command_id=cmd.id,
                command_name=cmd.command_name,
                payload={"document_id": str(did)},
            )
            return

        if cmd.command_name == ControlCommandName.KB_STATUS:
            did = UUID(str(cmd.args_json.get("document_id") or ""))
            doc = await studio_kb_service.get_document(session, did)
            if doc is None:
                mid = await reply("Документ не найден.")
            else:
                vers = await studio_kb_service.list_versions(session, did)
                lines = [f"KB status: {doc.title}\nid={doc.id} doc_status={doc.status}"]
                for v in vers[-20:]:
                    n = len(await studio_kb_service.list_chunks(session, v.id))
                    err = (v.last_error or "")[:120]
                    lines.append(
                        f"v{v.version_number} id={v.id} {v.status} chunks={n} parser={v.parser_name or '-'} err={err or '-'}"
                    )
                mid = await reply(_safe_truncate("\n".join(lines)))
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.KB_SEARCH:
            if not settings.studio_kb_embeddings_enabled:
                mid = await reply("Поиск по эмбеддингам выключен (STUDIO_KB_EMBEDDINGS_ENABLED=false).")
                cmd.status = ControlCommandStatus.PROCESSED
                cmd.processed_at = now
                cmd.response_telegram_message_id = mid
                return
            query = str(cmd.args_json.get("query") or "").strip()
            project_slug = str(cmd.args_json.get("project_slug") or "").strip()
            project_id = None
            if project_slug:
                proj = await studio_projects_service.get_project_by_slug(session, project_slug)
                if proj is None:
                    mid = await reply("Проект не найден.")
                    cmd.status = ControlCommandStatus.PROCESSED
                    cmd.processed_at = now
                    cmd.response_telegram_message_id = mid
                    return
                project_id = proj.id
            try:
                hits = await studio_kb_service.search_knowledge_chunks(
                    session,
                    settings,
                    query=query,
                    project_id=project_id,
                    top_k=settings.studio_kb_search_top_k,
                )
            except ValueError as exc:
                mid = await reply(f"Ошибка: {exc}")
                cmd.status = ControlCommandStatus.PROCESSED
                cmd.processed_at = now
                cmd.response_telegram_message_id = mid
                return
            lines = [f"KB search: найдено {len(hits)}, query={query!r}"]
            for h in hits:
                lines.append(
                    f"dist={h.distance:.4f} doc={h.document_id} chunk={h.chunk_id} idx={h.chunk_index}\n"
                    f"{(h.content_text or '')[:400]}"
                )
            mid = await reply(_safe_truncate("\n".join(lines)))
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            await _audit_control_command(
                session,
                action="control_commands.kb_search",
                command_id=cmd.id,
                command_name=cmd.command_name,
                payload={"query_len": len(query), "has_project": bool(project_slug)},
            )
            return

        if cmd.command_name == ControlCommandName.KB_ASK:
            if not settings.studio_kb_rag_enabled:
                mid = await reply("RAG по KB выключен (STUDIO_KB_RAG_ENABLED=false).")
                cmd.status = ControlCommandStatus.PROCESSED
                cmd.processed_at = now
                cmd.response_telegram_message_id = mid
                return
            if not settings.studio_kb_embeddings_enabled:
                mid = await reply("Поиск по эмбеддингам выключен (STUDIO_KB_EMBEDDINGS_ENABLED=false).")
                cmd.status = ControlCommandStatus.PROCESSED
                cmd.processed_at = now
                cmd.response_telegram_message_id = mid
                return
            question = str(cmd.args_json.get("query") or "").strip()
            project_slug = str(cmd.args_json.get("project_slug") or "").strip()
            project_id = None
            if project_slug:
                proj = await studio_projects_service.get_project_by_slug(session, project_slug)
                if proj is None:
                    mid = await reply("Проект не найден.")
                    cmd.status = ControlCommandStatus.PROCESSED
                    cmd.processed_at = now
                    cmd.response_telegram_message_id = mid
                    return
                project_id = proj.id
            try:
                result = await ask_knowledge_base(session, settings, question=question, project_id=project_id)
            except ValueError as exc:
                mid = await reply(f"Ошибка: {_redact_kb_error_message(str(exc), settings, token)}")
                cmd.status = ControlCommandStatus.PROCESSED
                cmd.processed_at = now
                cmd.response_telegram_message_id = mid
                return
            lines = [result.answer]
            if result.sources:
                lines.append("")
                lines.append(f"Источники ({len(result.sources)}):")
                for h in result.sources[:10]:
                    lines.append(
                        f"dist={h.distance:.4f} doc={h.document_id} chunk={h.chunk_id}\n{(h.content_text or '')[:350]}"
                    )
            mid = await reply(_safe_truncate("\n".join(lines)))
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            await _audit_control_command(
                session,
                action="control_commands.kb_ask",
                command_id=cmd.id,
                command_name=cmd.command_name,
                payload={"question_len": len(question), "has_project": bool(project_slug), "sources": len(result.sources)},
            )
            return

        if cmd.command_name == ControlCommandName.KB_ADD:
            title = str(cmd.args_json.get("title") or "")
            text_body = str(cmd.args_json.get("text") or "")
            doc = await studio_kb_service.create_document(session, title=title, source_type="manual")
            ver, created = await studio_kb_service.create_document_version_from_text(
                session, doc.id, text_body, settings
            )
            mid = await reply(
                f"Документ KB создан.\ndocument_id={doc.id}\nversion_id={ver.id} "
                f"version_number={ver.version_number} new={'да' if created else 'нет (тот же hash)'}"
            )
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            await _audit_control_command(
                session,
                action="control_commands.kb_add",
                command_id=cmd.id,
                command_name=cmd.command_name,
                payload={"document_id": str(doc.id), "version_id": str(ver.id)},
            )
            return

        cmd.status = ControlCommandStatus.IGNORED
        cmd.processed_at = now
        cmd.last_error = "unsupported kb command"
    except ValueError as exc:
        mid = await reply(f"Ошибка: {_redact_kb_error_message(str(exc), settings, token)}")
        cmd.status = ControlCommandStatus.PROCESSED
        cmd.processed_at = now
        cmd.response_telegram_message_id = mid
    except Exception as exc:  # noqa: BLE001
        logger.exception("kb control command failed id=%s", cmd.id)
        safe_err = _redact_kb_error_message(str(exc), settings, token)[:4000]
        cmd.status = ControlCommandStatus.FAILED
        cmd.last_error = safe_err
        cmd.processed_at = now
        try:
            await reply(f"KB: не выполнено: {_redact_kb_error_message(str(exc)[:500], settings, token)}")
        except Exception:  # noqa: BLE001
            pass


async def _dispatch_project_digest_control_commands(
    session: AsyncSession,
    cmd: StudioControlCommand,
    settings: Settings,
    reply,
    now: datetime,
) -> None:
    token = (settings.telegram_bot_token or "").strip()
    try:
        if cmd.command_name == ControlCommandName.UNKNOWN:
            reason = str(cmd.args_json.get("reason") or "")
            text_out = PROJECT_HELP_TEXT
            if reason:
                text_out = f"Ошибка: {reason}\n\n" + text_out
            mid = await reply(text_out)
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        slug = str(cmd.args_json.get("project_slug") or "")
        proj = await studio_projects_service.get_project_by_slug(session, slug)
        if proj is None:
            mid = await reply("Проект не найден.")
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.PROJECT_DIGEST_TODAY:
            p0, p1 = utc_today_period()
            row, _created = await project_digests_svc.generate_or_get_project_digest_for_period(
                session,
                project_id=proj.id,
                digest_type=ProjectDigestType.DAILY.value,
                period_start=p0,
                period_end=p1,
                settings=settings,
                summary_type_for_chats=SummaryType.DAILY,
            )
        elif cmd.command_name == ControlCommandName.PROJECT_DIGEST_YESTERDAY:
            p0, p1 = utc_yesterday_period()
            row, _created = await project_digests_svc.generate_or_get_project_digest_for_period(
                session,
                project_id=proj.id,
                digest_type=ProjectDigestType.DAILY.value,
                period_start=p0,
                period_end=p1,
                settings=settings,
                summary_type_for_chats=SummaryType.DAILY,
            )
        elif cmd.command_name == ControlCommandName.PROJECT_DIGEST_PERIOD:
            da = str(cmd.args_json.get("date_a") or "")
            db = str(cmd.args_json.get("date_b") or "")
            p0, p1 = period_bounds_utc(da, db)
            row, _created = await project_digests_svc.generate_or_get_project_digest_for_period(
                session,
                project_id=proj.id,
                digest_type=ProjectDigestType.MANUAL.value,
                period_start=p0,
                period_end=p1,
                settings=settings,
                summary_type_for_chats=SummaryType.MANUAL,
            )
        elif cmd.command_name == ControlCommandName.PROJECT_DIGEST_LATEST:
            row, _created = await project_digests_svc.generate_or_get_project_digest_latest(
                session,
                project_id=proj.id,
                settings=settings,
            )
        else:
            cmd.status = ControlCommandStatus.IGNORED
            cmd.processed_at = now
            cmd.last_error = "unsupported project_digest command"
            return

        snip = (row.digest_text or "")[:3500]
        body = (
            f"Дайджест проекта id={row.id}\n"
            f"slug={proj.slug} type={row.digest_type}\n"
            f"Повторная отправка: POST /project-digests/{row.id}/deliver-control-group\n\n"
            f"{snip}"
        )
        mid = await reply(_safe_truncate(body))
        mark_digest_delivered_from_control_command_reply(row, mid)
        cmd.status = ControlCommandStatus.PROCESSED
        cmd.processed_at = now
        cmd.response_telegram_message_id = mid
        await _audit_control_command(
            session,
            action="control_commands.project_digest",
            command_id=cmd.id,
            command_name=cmd.command_name,
            payload={"digest_id": str(row.id), "project_id": str(proj.id)},
        )
    except ValueError as exc:
        mid = await reply(f"Ошибка: {exc}")
        cmd.status = ControlCommandStatus.PROCESSED
        cmd.processed_at = now
        cmd.response_telegram_message_id = mid
    except Exception as exc:  # noqa: BLE001
        logger.exception("project digest command failed id=%s", cmd.id)
        safe_err = redact_secrets(str(exc), token)[:4000]
        cmd.status = ControlCommandStatus.FAILED
        cmd.last_error = safe_err
        cmd.processed_at = now
        try:
            await reply(f"Дайджест не выполнен: {redact_secrets(str(exc)[:500], token)}")
        except Exception:  # noqa: BLE001
            pass


async def _dispatch_project_control_commands(
    session: AsyncSession,
    cmd: StudioControlCommand,
    settings: Settings,
    reply,
    now: datetime,
) -> None:
    token = (settings.telegram_bot_token or "").strip()
    try:
        if cmd.command_name == ControlCommandName.UNKNOWN:
            reason = str(cmd.args_json.get("reason") or "")
            text_out = PROJECT_HELP_TEXT
            if reason:
                text_out = f"Ошибка: {reason}\n\n" + text_out
            mid = await reply(text_out)
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.PROJECT_HELP:
            mid = await reply(PROJECT_HELP_TEXT)
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            await _audit_control_command(
                session,
                action="control_commands.project_help",
                command_id=cmd.id,
                command_name=cmd.command_name,
                payload={},
            )
            return

        if cmd.command_name == ControlCommandName.PROJECT_LIST:
            rows = await studio_projects_service.list_projects(session, status=ProjectStatus.ACTIVE.value, limit=50)
            lines = ["Проекты (active):"]
            for proj in rows:
                lines.append(f"- {proj.slug} — {proj.name} (id={proj.id})")
            if not rows:
                lines.append("(пусто)")
            mid = await reply(_safe_truncate("\n".join(lines)))
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.PROJECT_CREATE:
            slug = str(cmd.args_json.get("slug") or "")
            name = str(cmd.args_json.get("name") or "")
            try:
                async with session.begin_nested():
                    row = await studio_projects_service.create_project(session, slug=slug, name=name)
            except IntegrityError:
                mid = await reply("Проект с таким slug уже существует.")
            except ValueError as exc:
                mid = await reply(f"Ошибка: {exc}")
            else:
                mid = await reply(f"Проект создан: {row.slug} — {row.name}\nid={row.id}")
                await _audit_control_command(
                    session,
                    action="control_commands.project_create",
                    command_id=cmd.id,
                    command_name=cmd.command_name,
                    payload={"project_id": str(row.id), "slug": row.slug},
                )
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name in (ControlCommandName.PROJECT_BIND, ControlCommandName.PROJECT_UNBIND):
            slug = str(cmd.args_json.get("project_slug") or "")
            chat_uid = UUID(str(cmd.args_json.get("chat_id") or ""))
            proj = await studio_projects_service.get_project_by_slug(session, slug)
            if proj is None:
                mid = await reply("Проект не найден.")
            elif cmd.command_name == ControlCommandName.PROJECT_BIND:
                try:
                    link, outcome = await studio_projects_service.bind_chat_to_project(
                        session,
                        project_id=proj.id,
                        chat_id=chat_uid,
                        role_in_project=RoleInProject.SECONDARY.value,
                    )
                    msg = {
                        "noop_active": "Чат уже привязан к проекту.",
                        "reactivated": "Связь восстановлена.",
                        "created": "Чат привязан.",
                    }.get(outcome, "Готово.")
                    mid = await reply(f"{msg}\nlink_id={link.id}")
                    await _audit_control_command(
                        session,
                        action="control_commands.project_bind",
                        command_id=cmd.id,
                        command_name=cmd.command_name,
                        payload={"project_id": str(proj.id), "chat_id": str(chat_uid), "outcome": outcome},
                    )
                except ValueError as exc:
                    mid = await reply(f"Ошибка: {exc}")
            else:
                row = await studio_projects_service.unbind_chat_from_project(
                    session, project_id=proj.id, chat_id=chat_uid
                )
                mid = await reply("Связь не найдена." if row is None else "Связь деактивирована.")
                if row is not None:
                    await _audit_control_command(
                        session,
                        action="control_commands.project_unbind",
                        command_id=cmd.id,
                        command_name=cmd.command_name,
                        payload={"project_id": str(proj.id), "chat_id": str(chat_uid)},
                    )
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        if cmd.command_name == ControlCommandName.PROJECT_CHATS:
            slug = str(cmd.args_json.get("project_slug") or "")
            proj = await studio_projects_service.get_project_by_slug(session, slug)
            if proj is None:
                mid = await reply("Проект не найден.")
            else:
                links = await studio_projects_service.list_project_chats(session, proj.id, active_only=True)
                lines = [f"Чаты проекта {proj.slug}:"]
                for ln in links:
                    ch = await session.get(StudioChat, ln.chat_id)
                    tg = ch.telegram_chat_id if ch else "?"
                    lines.append(f"- link={ln.id} chat={ln.chat_id} tg={tg} role={ln.role_in_project}")
                if not links:
                    lines.append("(нет активных привязок)")
                mid = await reply(_safe_truncate("\n".join(lines)))
            cmd.status = ControlCommandStatus.PROCESSED
            cmd.processed_at = now
            cmd.response_telegram_message_id = mid
            return

        cmd.status = ControlCommandStatus.IGNORED
        cmd.processed_at = now
        cmd.last_error = "unsupported project command"
    except Exception as exc:  # noqa: BLE001
        logger.exception("project command failed id=%s", cmd.id)
        safe_err = redact_secrets(str(exc), token)[:4000]
        cmd.status = ControlCommandStatus.FAILED
        cmd.last_error = safe_err
        cmd.processed_at = now
        try:
            await reply(f"Команда проектов не выполнена: {redact_secrets(str(exc)[:500], token)}")
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
