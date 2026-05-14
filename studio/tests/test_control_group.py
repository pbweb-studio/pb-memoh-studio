from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_group.constants import ChatRole, SystemNotificationStatus
from pb_studio.control_group.delivery_policy import assert_system_notification_not_sent_to_forbidden_chat
from pb_studio.control_group.models import StudioChatRole, StudioControlGroup, StudioSystemNotification
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import AuditLog, StudioChat
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def cg_engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def cg_client(cg_engine):
    factory = async_sessionmaker(cg_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:

        async def db_override():
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        app.dependency_overrides[get_db] = db_override
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session
        app.dependency_overrides.clear()


def _msg(update_id: int, chat_id: int = -100) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "T"},
            "from": {"id": 42, "is_bot": False, "first_name": "U"},
            "text": "hello",
        },
    }


@pytest.mark.asyncio
async def test_set_control_group_and_idempotent(cg_client):
    client, session = cg_client
    await client.post("/events/telegram", json=_msg(70001, chat_id=-501))
    r = await client.post("/control-group/set", json={"telegram_chat_id": -501})
    assert r.status_code == 200
    d = r.json()
    assert d["active"] is True
    r2 = await client.post("/control-group/set", json={"telegram_chat_id": -501})
    assert r2.status_code == 200
    n = await session.scalar(select(func.count()).select_from(StudioControlGroup))
    assert n == 1
    rows = (await session.scalars(select(StudioControlGroup))).all()
    assert sum(1 for x in rows if x.is_active) == 1


@pytest.mark.asyncio
async def test_switch_control_group_deactivates_previous(cg_client):
    client, session = cg_client
    await client.post("/events/telegram", json=_msg(70002, chat_id=-601))
    await client.post("/events/telegram", json=_msg(70003, chat_id=-602))
    await client.post("/control-group/set", json={"telegram_chat_id": -601})
    await client.post("/control-group/set", json={"telegram_chat_id": -602})
    active = (await session.scalars(select(StudioControlGroup).where(StudioControlGroup.is_active.is_(True)))).all()
    assert len(active) == 1
    chat_old = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -601))
    assert chat_old is not None
    assert chat_old.chat_role == ChatRole.UNKNOWN.value
    chat_new = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -602))
    assert chat_new.chat_role == ChatRole.CONTROL_GROUP.value


@pytest.mark.asyncio
async def test_chat_role_change_writes_audit(cg_client):
    client, session = cg_client
    await client.post("/events/telegram", json=_msg(70004, chat_id=-701))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -701))
    r = await client.post(f"/chats/{chat.id}/role", json={"role": "client_chat"})
    assert r.status_code == 200
    assert r.json()["chat_role"] == "client_chat"
    logs = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "control_group.chat_role_changed"))
    ).all()
    assert len(logs) >= 1
    hist = (await session.scalars(select(StudioChatRole).where(StudioChatRole.chat_id == chat.id))).all()
    assert any(h.role == "client_chat" for h in hist)


@pytest.mark.asyncio
async def test_my_chat_member_creates_notification_logged_only_without_control_group(cg_client):
    client, session = cg_client
    payload = {
        "update_id": 70005,
        "my_chat_member": {
            "chat": {"id": -801, "type": "supergroup", "title": "G"},
            "from": {"id": 1, "is_bot": False, "first_name": "A"},
            "old_chat_member": {"user": {"id": 99, "is_bot": True}, "status": "left"},
            "new_chat_member": {"user": {"id": 99, "is_bot": True}, "status": "member"},
        },
    }
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    n = await session.scalar(select(StudioSystemNotification).order_by(StudioSystemNotification.created_at.desc()))
    assert n is not None
    assert n.status == SystemNotificationStatus.LOGGED_ONLY.value
    assert n.source_telegram_chat_id == -801
    assert n.payload.get("delivery_policy") == "control_group_only"


@pytest.mark.asyncio
async def test_my_chat_member_notification_pending_with_control_group(cg_client):
    client, session = cg_client
    await client.post("/events/telegram", json=_msg(70006, chat_id=-901))
    await client.post("/control-group/set", json={"telegram_chat_id": -901})
    payload = {
        "update_id": 70007,
        "my_chat_member": {
            "chat": {"id": -902, "type": "supergroup", "title": "H"},
            "from": {"id": 1, "is_bot": False},
            "old_chat_member": {"user": {"id": 99, "is_bot": True}, "status": "left"},
            "new_chat_member": {"user": {"id": 99, "is_bot": True}, "status": "member"},
        },
    }
    await client.post("/events/telegram", json=payload)
    n = await session.scalar(
        select(StudioSystemNotification)
        .where(StudioSystemNotification.source_telegram_chat_id == -902)
        .order_by(StudioSystemNotification.created_at.desc())
    )
    assert n is not None
    assert n.status == SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value


def test_notification_delivery_policy_forbidden_for_client_chat():
    with pytest.raises(ValueError):
        assert_system_notification_not_sent_to_forbidden_chat(ChatRole.CLIENT_CHAT.value)
    assert_system_notification_not_sent_to_forbidden_chat(ChatRole.CONTROL_GROUP.value)


@pytest.mark.asyncio
async def test_cannot_set_control_group_role_via_chat_endpoint(cg_client):
    client, session = cg_client
    await client.post("/events/telegram", json=_msg(70008, chat_id=-1001))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -1001))
    r = await client.post(f"/chats/{chat.id}/role", json={"role": "control_group"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unassigned_chats(cg_client):
    client, session = cg_client
    await client.post("/events/telegram", json=_msg(70009, chat_id=-1101))
    await client.post("/events/telegram", json=_msg(70010, chat_id=-1102))
    chat2 = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -1102))
    await client.post(f"/chats/{chat2.id}/role", json={"role": "client_chat"})
    r = await client.get("/chats/unassigned")
    assert r.status_code == 200
    tids = {row["telegram_chat_id"] for row in r.json()}
    assert -1101 in tids
    assert -1102 not in tids


@pytest.mark.asyncio
async def test_admin_token_enforced(monkeypatch, cg_client):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "secret-token")
    get_settings.cache_clear()
    client, _session = cg_client
    r = await client.get("/control-group")
    assert r.status_code == 401
    r2 = await client.get("/control-group", headers={"Authorization": "Bearer secret-token"})
    assert r2.status_code == 200
    get_settings.cache_clear()
