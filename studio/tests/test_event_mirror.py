from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import ChatLifecycleEvent, StudioChat, StudioMessage, TelegramRawUpdate
from pb_studio.response_queue.models import Base, InboundMessage


@pytest_asyncio.fixture
async def mirror_engine():
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
async def mirror_client(mirror_engine):
    factory = async_sessionmaker(mirror_engine, class_=AsyncSession, expire_on_commit=False)
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


def _msg(update_id: int, chat_id: int = -100, user_id: int = 42, text: str = "hello") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "T"},
            "from": {"id": user_id, "is_bot": False, "first_name": "U"},
            "text": text,
        },
    }


@pytest.mark.asyncio
async def test_post_telegram_saves_raw_update(mirror_client):
    client, session = mirror_client
    payload = _msg(10001)
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["duplicate"] is False
    assert data["enqueue"] is None
    raw = await session.get(TelegramRawUpdate, UUID(data["telegram_raw_update_id"]))
    assert raw is not None
    assert raw.update_id == 10001
    assert raw.payload["message"]["text"] == "hello"


@pytest.mark.asyncio
async def test_duplicate_update_id_idempotent(mirror_client):
    client, session = mirror_client
    payload = _msg(10002)
    r1 = await client.post("/events/telegram", json=payload)
    r2 = await client.post("/events/telegram", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["telegram_raw_update_id"] == r2.json()["telegram_raw_update_id"]
    assert r2.json()["duplicate"] is True
    count = await session.scalar(select(func.count()).select_from(TelegramRawUpdate).where(TelegramRawUpdate.update_id == 10002))
    assert count == 1


@pytest.mark.asyncio
async def test_message_creates_chat_user_message_row(mirror_client):
    client, session = mirror_client
    r = await client.post("/events/telegram", json=_msg(10003, chat_id=-200, user_id=99))
    assert r.status_code == 200
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -200))
    assert chat is not None
    assert chat.chat_type == "supergroup"
    assert chat.title == "T"
    msg = await session.scalar(select(StudioMessage).where(StudioMessage.telegram_message_id == 1))
    assert msg is not None
    assert msg.text == "hello"


@pytest.mark.asyncio
async def test_my_chat_member_creates_lifecycle(mirror_client):
    client, session = mirror_client
    payload = {
        "update_id": 10004,
        "my_chat_member": {
            "chat": {"id": -300, "type": "supergroup", "title": "G"},
            "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
            "old_chat_member": {"user": {"id": 1, "is_bot": True}, "status": "left"},
            "new_chat_member": {"user": {"id": 1, "is_bot": True}, "status": "administrator"},
        },
    }
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    ev = await session.scalar(
        select(ChatLifecycleEvent).where(ChatLifecycleEvent.event_type == "my_chat_member")
    )
    assert ev is not None
    assert ev.old_member_status == "left"
    assert ev.new_member_status == "administrator"


@pytest.mark.asyncio
async def test_new_chat_members_and_left_member(mirror_client):
    client, session = mirror_client
    payload = {
        "update_id": 10005,
        "message": {
            "message_id": 2,
            "date": 1700000001,
            "chat": {"id": -400, "type": "group", "title": "Grp"},
            "from": {"id": 10, "is_bot": False, "first_name": "A"},
            "new_chat_members": [{"id": 20, "is_bot": False, "first_name": "B"}],
            "left_chat_member": {"id": 30, "is_bot": False, "first_name": "C"},
            "text": "welcome",
        },
    }
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    raw_uid = UUID(r.json()["telegram_raw_update_id"])
    types = (
        await session.scalars(
            select(ChatLifecycleEvent.event_type).where(ChatLifecycleEvent.raw_update_id == raw_uid)
        )
    ).all()
    assert "new_chat_members" in types
    assert "left_chat_member" in types


@pytest.mark.asyncio
async def test_migrate_events(mirror_client):
    client, session = mirror_client
    payload = {
        "update_id": 10006,
        "message": {
            "message_id": 3,
            "date": 1700000002,
            "chat": {"id": -500, "type": "supergroup", "title": "Old"},
            "migrate_to_chat_id": -999,
            "migrate_from_chat_id": -888,
            "from": {"id": 1, "is_bot": False, "first_name": "U"},
            "text": "migrated",
        },
    }
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    raw_id = UUID(r.json()["telegram_raw_update_id"])
    rows = (
        await session.scalars(
            select(ChatLifecycleEvent.event_type).where(ChatLifecycleEvent.raw_update_id == raw_id)
        )
    ).all()
    assert "migrate_to_chat_id" in rows
    assert "migrate_from_chat_id" in rows


@pytest.mark.asyncio
async def test_unsupported_valid_update_stores_raw_only(mirror_client):
    client, session = mirror_client
    payload = {
        "update_id": 10007,
        "shipping_query": {
            "id": "sq1",
            "from": {"id": 1, "is_bot": False},
            "invoice_payload": "x",
            "shipping_address": {"country_code": "FI"},
        },
    }
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    raw = await session.scalar(select(TelegramRawUpdate).where(TelegramRawUpdate.update_id == 10007))
    assert raw is not None
    assert "shipping_query" in raw.payload


@pytest.mark.asyncio
async def test_edited_message_updates_row(mirror_client):
    client, session = mirror_client
    await client.post(
        "/events/telegram",
        json={
            "update_id": 10008,
            "message": {
                "message_id": 5,
                "date": 1700000003,
                "chat": {"id": -600, "type": "private"},
                "from": {"id": 55, "is_bot": False, "first_name": "Me"},
                "text": "v1",
            },
        },
    )
    await client.post(
        "/events/telegram",
        json={
            "update_id": 10009,
            "edited_message": {
                "message_id": 5,
                "date": 1700000004,
                "chat": {"id": -600, "type": "private"},
                "from": {"id": 55, "is_bot": False, "first_name": "Me"},
                "text": "v2",
            },
        },
    )
    msg = await session.scalar(select(StudioMessage).where(StudioMessage.telegram_message_id == 5))
    assert msg is not None
    assert msg.text == "v2"


@pytest.mark.asyncio
async def test_optional_enqueue_user_message(monkeypatch, mirror_client):
    monkeypatch.setenv("STUDIO_MIRROR_ENQUEUE_USER_MESSAGES", "true")
    get_settings.cache_clear()
    try:
        client, session = mirror_client
        r = await client.post("/events/telegram", json=_msg(10010, chat_id=-700))
        assert r.status_code == 200
        assert r.json()["enqueue"] is not None
        assert r.json()["enqueue"]["duplicate"] is False
        inbound_count = await session.scalar(select(func.count()).select_from(InboundMessage))
        assert inbound_count == 1
    finally:
        monkeypatch.delenv("STUDIO_MIRROR_ENQUEUE_USER_MESSAGES", raising=False)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ingest_token_required(monkeypatch, mirror_client):
    monkeypatch.setenv("STUDIO_EVENTS_INGEST_TOKEN", "secret-token")
    get_settings.cache_clear()
    try:
        client, _ = mirror_client
        r = await client.post("/events/telegram", json=_msg(10011))
        assert r.status_code == 401
        r2 = await client.post(
            "/events/telegram",
            json=_msg(10012),
            headers={"Authorization": "Bearer secret-token"},
        )
        assert r2.status_code == 200
    finally:
        monkeypatch.delenv("STUDIO_EVENTS_INGEST_TOKEN", raising=False)
        get_settings.cache_clear()


def test_no_api_telegram_org_in_event_mirror_sources():
    import inspect

    import pb_studio.event_mirror.service as svc

    src = inspect.getsource(svc)
    assert "api.telegram.org" not in src


@pytest.mark.asyncio
async def test_new_chat_title_lifecycle(mirror_client):
    client, session = mirror_client
    payload = {
        "update_id": 10013,
        "message": {
            "message_id": 6,
            "date": 1700000005,
            "chat": {"id": -800, "type": "supergroup", "title": "OldTitle"},
            "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
            "new_chat_title": "NewTitle",
        },
    }
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    ev = await session.scalar(
        select(ChatLifecycleEvent).where(ChatLifecycleEvent.event_type == "new_chat_title")
    )
    assert ev is not None


@pytest.mark.asyncio
async def test_callback_query_normalizes(mirror_client):
    client, session = mirror_client
    payload = {
        "update_id": 10014,
        "callback_query": {
            "id": "cb1",
            "from": {"id": 7, "is_bot": False, "first_name": "U"},
            "message": {
                "message_id": 10,
                "date": 1700000010,
                "chat": {"id": -900, "type": "supergroup", "title": "Q"},
                "text": "menu",
            },
            "data": "x:1",
        },
    }
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    ev = await session.scalar(
        select(ChatLifecycleEvent).where(ChatLifecycleEvent.event_type == "callback_query")
    )
    assert ev is not None
    msg = await session.scalar(select(StudioMessage).where(StudioMessage.telegram_message_id == 10))
    assert msg is not None


@pytest.mark.asyncio
async def test_chat_member_lifecycle(mirror_client):
    client, session = mirror_client
    payload = {
        "update_id": 10015,
        "chat_member": {
            "chat": {"id": -901, "type": "supergroup", "title": "G"},
            "from": {"id": 2, "is_bot": False, "first_name": "Admin"},
            "date": 1700000011,
            "old_chat_member": {"user": {"id": 3, "is_bot": False}, "status": "left"},
            "new_chat_member": {"user": {"id": 3, "is_bot": False}, "status": "member"},
        },
    }
    r = await client.post("/events/telegram", json=payload)
    assert r.status_code == 200
    ev = await session.scalar(select(ChatLifecycleEvent).where(ChatLifecycleEvent.event_type == "chat_member"))
    assert ev is not None
    assert ev.old_member_status == "left"
    assert ev.new_member_status == "member"


@pytest.mark.asyncio
async def test_missing_update_id_returns_400(mirror_client):
    client, _ = mirror_client
    r = await client.post("/events/telegram", json={"message": {}})
    assert r.status_code == 400
