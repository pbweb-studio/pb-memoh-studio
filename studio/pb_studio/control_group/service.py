from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole, SystemNotificationStatus
from pb_studio.control_group.models import StudioChatRole, StudioControlGroup, StudioSystemNotification
from pb_studio.event_mirror.models import AuditLog, ChatLifecycleEvent, StudioChat, TelegramRawUpdate


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


async def get_active_control_group(session: AsyncSession) -> StudioControlGroup | None:
    return await session.scalar(select(StudioControlGroup).where(StudioControlGroup.is_active.is_(True)))


async def get_control_group_chat(session: AsyncSession) -> StudioChat | None:
    row = await get_active_control_group(session)
    if row is None:
        return None
    return await session.get(StudioChat, row.chat_id)


async def append_role_history(session: AsyncSession, *, chat_id: UUID, role: str, now: datetime) -> None:
    session.add(StudioChatRole(chat_id=chat_id, role=role, created_at=now))


async def set_chat_role(
    session: AsyncSession,
    *,
    studio_chat_id: UUID,
    role: str,
    now: datetime | None = None,
) -> StudioChat:
    now = now or utcnow()
    if role not in {m.value for m in ChatRole}:
        raise ValueError(f"invalid chat role: {role!r}")
    if role == ChatRole.CONTROL_GROUP.value:
        raise ValueError("assign control group via POST /control-group/set, not via chat role endpoint")
    chat = await session.get(StudioChat, studio_chat_id)
    if chat is None:
        raise ValueError("chat not found")
    prev = chat.chat_role
    chat.chat_role = role
    chat.updated_at = now
    await append_role_history(session, chat_id=chat.id, role=role, now=now)
    await _audit(
        session,
        action="control_group.chat_role_changed",
        entity_type="studio_chat",
        entity_id=str(chat.id),
        payload={"telegram_chat_id": chat.telegram_chat_id, "previous": prev, "role": role},
    )
    return chat


async def set_control_group_by_telegram_id(
    session: AsyncSession,
    telegram_chat_id: int,
    *,
    now: datetime | None = None,
) -> StudioControlGroup:
    now = now or utcnow()
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == telegram_chat_id))
    if chat is None:
        raise ValueError("unknown telegram_chat_id; ingest an update from this chat first")

    current = await get_active_control_group(session)
    if current is not None and current.chat_id == chat.id:
        return current

    prev_rows = (await session.scalars(select(StudioControlGroup).where(StudioControlGroup.is_active.is_(True)))).all()
    for pr in prev_rows:
        pr.is_active = False
        pr.deactivated_at = now
        prev_chat = await session.get(StudioChat, pr.chat_id)
        if prev_chat is not None and prev_chat.chat_role == ChatRole.CONTROL_GROUP.value:
            prev_chat.chat_role = ChatRole.UNKNOWN.value
            prev_chat.updated_at = now
            await append_role_history(
                session, chat_id=prev_chat.id, role=ChatRole.UNKNOWN.value, now=now
            )

    chat.chat_role = ChatRole.CONTROL_GROUP.value
    chat.updated_at = now
    await append_role_history(session, chat_id=chat.id, role=ChatRole.CONTROL_GROUP.value, now=now)

    cg = StudioControlGroup(chat_id=chat.id, is_active=True, created_at=now)
    session.add(cg)
    await session.flush()

    await _audit(
        session,
        action="control_group.set",
        entity_type="studio_control_group",
        entity_id=str(cg.id),
        payload={"telegram_chat_id": telegram_chat_id, "studio_chat_id": str(chat.id)},
    )
    return cg


async def record_my_chat_member_system_notification(
    session: AsyncSession,
    *,
    raw: TelegramRawUpdate,
    chat_row: StudioChat,
    block: dict[str, Any],
    now: datetime | None = None,
) -> StudioSystemNotification:
    """Persist system notification; never targets source chat for delivery (Phase 5a: DB only)."""
    now = now or utcnow()
    active = await get_active_control_group(session)
    st = (
        SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY
        if active
        else SystemNotificationStatus.LOGGED_ONLY
    )
    le = await session.scalar(
        select(ChatLifecycleEvent)
        .where(
            ChatLifecycleEvent.raw_update_id == raw.id,
            ChatLifecycleEvent.event_type == "my_chat_member",
        )
        .order_by(ChatLifecycleEvent.created_at.desc())
        .limit(1)
    )
    old_m = block.get("old_chat_member") or {}
    new_m = block.get("new_chat_member") or {}
    title = "Telegram: my_chat_member (bot)"
    body = f"status {old_m.get('status')!r} → {new_m.get('status')!r}"
    payload = {
        "delivery_policy": "control_group_only",
        "forbidden_targets": ["source_chat", "client_chat", "project_chat"],
        "old_chat_member": old_m,
        "new_chat_member": new_m,
    }
    row = StudioSystemNotification(
        kind="my_chat_member",
        source_telegram_chat_id=chat_row.telegram_chat_id,
        source_studio_chat_id=chat_row.id,
        lifecycle_event_id=le.id if le else None,
        raw_update_id=raw.id,
        title=title,
        body=body,
        payload=payload,
        status=st.value,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    await _audit(
        session,
        action="control_group.system_notification_created",
        entity_type="studio_system_notification",
        entity_id=str(row.id),
        payload={"kind": row.kind, "status": row.status, "source_telegram_chat_id": chat_row.telegram_chat_id},
    )
    return row


async def list_chats(session: AsyncSession, *, unassigned_only: bool = False) -> list[StudioChat]:
    q = select(StudioChat).order_by(StudioChat.telegram_chat_id)
    if unassigned_only:
        q = q.where(StudioChat.chat_role == ChatRole.UNKNOWN.value)
    return list((await session.scalars(q)).all())
