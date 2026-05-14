from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.event_mirror.models import AuditLog, ChatLifecycleEvent, StudioChat, StudioMessage, StudioTelegramUser, TelegramRawUpdate
from pb_studio.response_queue.schemas import EnqueueResult, InboundEnqueue
from pb_studio.response_queue.service import QueueService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_minimal_telegram_update(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    if "update_id" not in payload:
        raise ValueError("update_id is required")
    uid = payload["update_id"]
    if not isinstance(uid, int):
        raise ValueError("update_id must be an integer")
    return uid


async def _audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
    )


async def _upsert_chat(session: AsyncSession, chat: dict[str, Any], *, now: datetime) -> StudioChat:
    tid = int(chat["id"])
    row = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == tid))
    extra: dict[str, Any] = {}
    for key in ("description", "invite_link", "slow_mode_delay", "message_auto_delete_time"):
        if key in chat and chat[key] is not None:
            extra[key] = chat[key]
    title = chat.get("title")
    username = chat.get("username")
    ctype = str(chat.get("type") or "unknown")
    if row is None:
        row = StudioChat(
            telegram_chat_id=tid,
            chat_type=ctype,
            title=title,
            username=username,
            extra=extra or None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row
    row.chat_type = ctype
    row.title = title if title is not None else row.title
    row.username = username if username is not None else row.username
    if extra:
        merged = dict(row.extra or {})
        merged.update(extra)
        row.extra = merged
    row.updated_at = now
    await session.flush()
    return row


async def _upsert_user(session: AsyncSession, user: dict[str, Any], *, now: datetime) -> StudioTelegramUser:
    uid = int(user["id"])
    row = await session.scalar(select(StudioTelegramUser).where(StudioTelegramUser.telegram_user_id == uid))
    if row is None:
        row = StudioTelegramUser(
            telegram_user_id=uid,
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            is_bot=bool(user.get("is_bot", False)),
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row
    row.username = user.get("username", row.username)
    row.first_name = user.get("first_name", row.first_name)
    row.last_name = user.get("last_name", row.last_name)
    row.is_bot = bool(user.get("is_bot", row.is_bot))
    row.updated_at = now
    await session.flush()
    return row


async def _upsert_message(
    session: AsyncSession,
    *,
    chat_row: StudioChat,
    raw: TelegramRawUpdate,
    inner: dict[str, Any],
    now: datetime,
) -> StudioMessage:
    mid = int(inner["message_id"])
    msg_date = datetime.fromtimestamp(int(inner["date"]), tz=timezone.utc)
    text = inner.get("text")
    caption = inner.get("caption")
    existing = await session.scalar(
        select(StudioMessage).where(
            StudioMessage.chat_id == chat_row.id,
            StudioMessage.telegram_message_id == mid,
        )
    )
    if existing is None:
        row = StudioMessage(
            chat_id=chat_row.id,
            raw_update_id=raw.id,
            telegram_message_id=mid,
            date=msg_date,
            text=text,
            caption=caption,
            raw_message=dict(inner),
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row
    existing.date = msg_date
    existing.text = text
    existing.caption = caption
    existing.raw_message = dict(inner)
    existing.raw_update_id = raw.id
    existing.updated_at = now
    await session.flush()
    return existing


async def _add_lifecycle(
    session: AsyncSession,
    *,
    chat_row: StudioChat | None,
    raw: TelegramRawUpdate,
    event_type: str,
    old_member_status: str | None = None,
    new_member_status: str | None = None,
    actor_telegram_user_id: int | None = None,
    actor_is_bot: bool | None = None,
    raw_fragment: dict[str, Any] | None = None,
    now: datetime,
) -> None:
    session.add(
        ChatLifecycleEvent(
            chat_id=chat_row.id if chat_row else None,
            raw_update_id=raw.id,
            event_type=event_type,
            old_member_status=old_member_status,
            new_member_status=new_member_status,
            actor_telegram_user_id=actor_telegram_user_id,
            actor_is_bot=actor_is_bot,
            raw_fragment=raw_fragment,
            created_at=now,
        )
    )


async def _normalize_message_inner(
    session: AsyncSession,
    raw: TelegramRawUpdate,
    inner: dict[str, Any],
    *,
    now: datetime,
    is_edited: bool,
) -> None:
    chat_row = await _upsert_chat(session, inner["chat"], now=now)
    if "from" in inner:
        await _upsert_user(session, inner["from"], now=now)
    await _upsert_message(session, chat_row=chat_row, raw=raw, inner=inner, now=now)

    if inner.get("new_chat_members"):
        for member in inner["new_chat_members"]:
            await _upsert_user(session, member, now=now)
            await _add_lifecycle(
                session,
                chat_row=chat_row,
                raw=raw,
                event_type="new_chat_members",
                new_member_status="member",
                actor_telegram_user_id=int(member["id"]),
                actor_is_bot=bool(member.get("is_bot")),
                raw_fragment={"member": member},
                now=now,
            )
    if inner.get("left_chat_member"):
        lm = inner["left_chat_member"]
        await _upsert_user(session, lm, now=now)
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="left_chat_member",
            actor_telegram_user_id=int(lm["id"]),
            actor_is_bot=bool(lm.get("is_bot")),
            raw_fragment={"left_chat_member": lm},
            now=now,
        )
    if inner.get("migrate_to_chat_id") is not None:
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="migrate_to_chat_id",
            raw_fragment={"migrate_to_chat_id": int(inner["migrate_to_chat_id"])},
            now=now,
        )
    if inner.get("migrate_from_chat_id") is not None:
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="migrate_from_chat_id",
            raw_fragment={"migrate_from_chat_id": int(inner["migrate_from_chat_id"])},
            now=now,
        )
    if inner.get("new_chat_title") is not None:
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="new_chat_title",
            raw_fragment={"new_chat_title": inner.get("new_chat_title"), "chat": inner.get("chat")},
            now=now,
        )
    if inner.get("new_chat_photo") is not None:
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="new_chat_photo",
            raw_fragment={"fragment": "new_chat_photo"},
            now=now,
        )
    if inner.get("delete_chat_photo"):
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="delete_chat_photo",
            raw_fragment={},
            now=now,
        )
    if inner.get("group_chat_created"):
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="group_chat_created",
            raw_fragment={},
            now=now,
        )
    if inner.get("supergroup_chat_created"):
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="supergroup_chat_created",
            raw_fragment={},
            now=now,
        )
    if inner.get("channel_chat_created"):
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="channel_chat_created",
            raw_fragment={},
            now=now,
        )

    if is_edited:
        await _add_lifecycle(
            session,
            chat_row=chat_row,
            raw=raw,
            event_type="edited_message",
            raw_fragment={"message_id": inner.get("message_id")},
            now=now,
        )


async def _normalize_my_chat_member(session: AsyncSession, raw: TelegramRawUpdate, block: dict[str, Any], *, now: datetime) -> None:
    chat_row = await _upsert_chat(session, block["chat"], now=now)
    actor = block.get("from")
    if actor:
        await _upsert_user(session, actor, now=now)
    old_m = block.get("old_chat_member") or {}
    new_m = block.get("new_chat_member") or {}
    await _add_lifecycle(
        session,
        chat_row=chat_row,
        raw=raw,
        event_type="my_chat_member",
        old_member_status=old_m.get("status"),
        new_member_status=new_m.get("status"),
        actor_telegram_user_id=int(actor["id"]) if actor else None,
        actor_is_bot=bool(actor.get("is_bot")) if actor else None,
        raw_fragment={"old_chat_member": old_m, "new_chat_member": new_m},
        now=now,
    )


async def _normalize_chat_member(session: AsyncSession, raw: TelegramRawUpdate, block: dict[str, Any], *, now: datetime) -> None:
    chat_row = await _upsert_chat(session, block["chat"], now=now)
    actor = block.get("from")
    if actor:
        await _upsert_user(session, actor, now=now)
    old_m = block.get("old_chat_member") or {}
    new_m = block.get("new_chat_member") or {}
    await _add_lifecycle(
        session,
        chat_row=chat_row,
        raw=raw,
        event_type="chat_member",
        old_member_status=old_m.get("status"),
        new_member_status=new_m.get("status"),
        actor_telegram_user_id=int(actor["id"]) if actor else None,
        actor_is_bot=bool(actor.get("is_bot")) if actor else None,
        raw_fragment={"date": block.get("date"), "old": old_m, "new": new_m},
        now=now,
    )


async def _normalize_callback_query(session: AsyncSession, raw: TelegramRawUpdate, cq: dict[str, Any], *, now: datetime) -> None:
    chat_row = None
    if cq.get("message") and isinstance(cq["message"], dict) and cq["message"].get("chat"):
        await _normalize_message_inner(session, raw, cq["message"], now=now, is_edited=False)
        chat_row = await session.scalar(
            select(StudioChat).where(
                StudioChat.telegram_chat_id == int(cq["message"]["chat"]["id"]),
            )
        )
    actor = cq.get("from")
    if actor:
        await _upsert_user(session, actor, now=now)
    await _add_lifecycle(
        session,
        chat_row=chat_row,
        raw=raw,
        event_type="callback_query",
        actor_telegram_user_id=int(actor["id"]) if actor else None,
        actor_is_bot=bool(actor.get("is_bot")) if actor else None,
        raw_fragment={"id": cq.get("id"), "data": cq.get("data"), "inline_message_id": cq.get("inline_message_id")},
        now=now,
    )


def _enqueue_candidate_message(inner: dict[str, Any]) -> InboundEnqueue | None:
    body = (inner.get("text") or inner.get("caption") or "").strip()
    if not body:
        return None
    chat = inner.get("chat") or {}
    ctype = str(chat.get("type") or "")
    if ctype not in ("private", "group", "supergroup"):
        return None
    from_user = inner.get("from")
    if not from_user or from_user.get("is_bot"):
        return None
    chat_id = int(chat["id"])
    mid = inner.get("message_id")
    if mid is None:
        return None
    return InboundEnqueue(
        telegram_chat_id=chat_id,
        body_text=body,
        telegram_message_id=str(mid),
        sender_id=str(from_user["id"]),
        raw_payload=dict(inner),
    )


async def ingest_telegram_update(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    queue: QueueService | None = None,
    mirror_enqueue_user_messages: bool = False,
    now: datetime | None = None,
) -> tuple[TelegramRawUpdate, bool, EnqueueResult | None]:
    """
    Persist raw update; normalize known branches. Idempotent on update_id.
    Returns (raw_row, duplicate, enqueue_result).
    """
    now = now or utcnow()
    update_id = validate_minimal_telegram_update(payload)
    existing = await session.scalar(select(TelegramRawUpdate).where(TelegramRawUpdate.update_id == update_id))
    if existing is not None:
        await _audit(
            session,
            action="event_mirror.duplicate",
            entity_type="telegram_raw_update",
            entity_id=str(existing.id),
            payload={"update_id": update_id},
        )
        return existing, True, None

    raw = TelegramRawUpdate(update_id=update_id, payload=dict(payload), created_at=now)
    session.add(raw)
    await session.flush()

    await _audit(
        session,
        action="event_mirror.ingest",
        entity_type="telegram_raw_update",
        entity_id=str(raw.id),
        payload={"update_id": update_id},
    )

    enqueue_result: EnqueueResult | None = None
    handled = False

    if "message" in payload and isinstance(payload["message"], dict):
        handled = True
        inner = payload["message"]
        await _normalize_message_inner(session, raw, inner, now=now, is_edited=False)
        if mirror_enqueue_user_messages and queue is not None:
            cand = _enqueue_candidate_message(inner)
            if cand is not None:
                enqueue_result = await queue.enqueue(session, cand, now=now)

    elif "edited_message" in payload and isinstance(payload["edited_message"], dict):
        handled = True
        inner = payload["edited_message"]
        await _normalize_message_inner(session, raw, inner, now=now, is_edited=True)
        if mirror_enqueue_user_messages and queue is not None:
            cand = _enqueue_candidate_message(inner)
            if cand is not None:
                enqueue_result = await queue.enqueue(session, cand, now=now)

    elif "callback_query" in payload and isinstance(payload["callback_query"], dict):
        handled = True
        await _normalize_callback_query(session, raw, payload["callback_query"], now=now)

    elif "my_chat_member" in payload and isinstance(payload["my_chat_member"], dict):
        handled = True
        await _normalize_my_chat_member(session, raw, payload["my_chat_member"], now=now)

    elif "chat_member" in payload and isinstance(payload["chat_member"], dict):
        handled = True
        await _normalize_chat_member(session, raw, payload["chat_member"], now=now)

    if not handled:
        await _audit(
            session,
            action="event_mirror.unsupported_shape",
            entity_type="telegram_raw_update",
            entity_id=str(raw.id),
            payload={"keys": [k for k in payload.keys() if k != "update_id"]},
        )

    return raw, False, enqueue_result
