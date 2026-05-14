from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_group.constants import ChatRole, SystemNotificationStatus
from pb_studio.control_group.models import StudioSystemNotification
from pb_studio.control_group.system_notification_delivery import deliver_pending_batch
from pb_studio.core.config import Settings, get_settings
from pb_studio.event_mirror.models import AuditLog, StudioChat
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def del_engine():
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
async def del_client(del_engine):
    factory = async_sessionmaker(del_engine, class_=AsyncSession, expire_on_commit=False)
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


def _settings_delivery(**kwargs: object) -> Settings:
    data = dict(
        studio_system_notifications_enabled=True,
        telegram_bot_token="BOT_SECRET_XYZ",
        studio_telegram_send_timeout_ms=3000,
        studio_system_notification_max_retries=3,
    )
    data.update(kwargs)
    return Settings.model_validate(data)


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
async def test_delivery_disabled_noop(del_client):
    client, session = del_client
    await client.post("/events/telegram", json=_msg(80001, chat_id=-2001))
    await client.post("/control-group/set", json={"telegram_chat_id": -2001})
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -2001))
    session.add(
        StudioSystemNotification(
            kind="t",
            source_telegram_chat_id=-3000,
            source_studio_chat_id=chat.id,
            status=SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value,
            title="x",
            body="y",
            payload={},
        )
    )
    await session.commit()
    s = _settings_delivery(studio_system_notifications_enabled=False)
    counts = await deliver_pending_batch(session, settings=s, send_message=AsyncMock(return_value=(True, 200, "", 42)))
    assert counts["delivered"] == 0
    n = await session.scalar(select(StudioSystemNotification).order_by(StudioSystemNotification.created_at.desc()))
    assert n.status == SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value


@pytest.mark.asyncio
async def test_delivery_success_mock(del_client):
    client, session = del_client
    await client.post("/events/telegram", json=_msg(80002, chat_id=-2002))
    await client.post("/control-group/set", json={"telegram_chat_id": -2002})
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -2002))
    session.add(
        StudioSystemNotification(
            kind="t",
            source_telegram_chat_id=-3002,
            source_studio_chat_id=chat.id,
            status=SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value,
            title="Hi",
            body="Body",
            payload={},
        )
    )
    await session.commit()
    mock = AsyncMock(return_value=(True, 200, "", 99))
    s = _settings_delivery()
    counts = await deliver_pending_batch(session, settings=s, send_message=mock)
    assert counts["delivered"] == 1
    mock.assert_awaited()
    _args, kwargs = mock.await_args
    assert kwargs["chat_id"] == -2002
    # Токен передаётся в sendMessage — это ожидаемо; утечки в логи проверяются в test_audit_logs_redact_token.


@pytest.mark.asyncio
async def test_delivery_500_retryable_then_permanent(del_client):
    client, session = del_client
    await client.post("/events/telegram", json=_msg(80003, chat_id=-2003))
    await client.post("/control-group/set", json={"telegram_chat_id": -2003})
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -2003))
    nid = uuid.uuid4()
    session.add(
        StudioSystemNotification(
            id=nid,
            kind="t",
            source_telegram_chat_id=-3003,
            source_studio_chat_id=chat.id,
            status=SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value,
            title="t",
            body="b",
            payload={},
        )
    )
    await session.commit()
    s = _settings_delivery(studio_system_notification_max_retries=2)
    mock = AsyncMock(return_value=(False, 500, "internal", None))
    c1 = await deliver_pending_batch(session, settings=s, send_message=mock)
    assert c1["failed_retryable"] == 1
    await session.commit()
    row = await session.get(StudioSystemNotification, nid)
    assert row.status == SystemNotificationStatus.FAILED_RETRYABLE.value
    assert row.retry_count == 1
    c2 = await deliver_pending_batch(session, settings=s, send_message=mock)
    assert c2["failed_permanent"] == 1
    await session.commit()
    row = await session.get(StudioSystemNotification, nid)
    assert row.status == SystemNotificationStatus.FAILED_PERMANENT.value


@pytest.mark.asyncio
async def test_delivery_blocked_wrong_destination_role(del_client):
    client, session = del_client
    await client.post("/events/telegram", json=_msg(80004, chat_id=-2004))
    await client.post("/control-group/set", json={"telegram_chat_id": -2004})
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -2004))
    chat.chat_role = ChatRole.CLIENT_CHAT.value
    await session.commit()
    mock = AsyncMock(return_value=(True, 200, "", None))
    s = _settings_delivery()
    counts = await deliver_pending_batch(session, settings=s, send_message=mock)
    assert counts["skipped"] == 1
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_audit_logs_redact_token(del_client):
    client, session = del_client
    await client.post("/events/telegram", json=_msg(80005, chat_id=-2005))
    await client.post("/control-group/set", json={"telegram_chat_id": -2005})
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -2005))
    session.add(
        StudioSystemNotification(
            kind="t",
            source_telegram_chat_id=-3005,
            source_studio_chat_id=chat.id,
            status=SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value,
            title="e",
            body="e",
            payload={},
        )
    )
    await session.commit()

    async def bad_send(**kwargs: object) -> tuple[bool, int | None, str, int | None]:
        return False, 400, "bad BOT_SECRET_XYZ token", None

    s = _settings_delivery(telegram_bot_token="BOT_SECRET_XYZ")
    await deliver_pending_batch(session, settings=s, send_message=bad_send)
    await session.commit()
    logs = (await session.scalars(select(AuditLog))).all()
    blob = " ".join(str(l.payload) for l in logs if l.payload)
    assert "BOT_SECRET_XYZ" not in blob


@pytest.mark.asyncio
async def test_post_deliver_pending_endpoint(del_client, monkeypatch):
    client, session = del_client
    await client.post("/events/telegram", json=_msg(80006, chat_id=-2006))
    await client.post("/control-group/set", json={"telegram_chat_id": -2006})
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -2006))
    session.add(
        StudioSystemNotification(
            kind="t",
            source_telegram_chat_id=-3006,
            source_studio_chat_id=chat.id,
            status=SystemNotificationStatus.PENDING_FOR_CONTROL_GROUP_DELIVERY.value,
            title="API",
            body="test",
            payload={},
        )
    )
    await session.commit()

    async def ok_send(**kwargs: object) -> tuple[bool, int | None, str, int | None]:
        return True, 200, "", 555

    monkeypatch.setattr(
        "pb_studio.control_group.system_notification_delivery.telegram_send_message",
        ok_send,
    )

    def fake_settings() -> Settings:
        return _settings_delivery()

    app.dependency_overrides[get_settings] = fake_settings
    try:
        r = await client.post("/notifications/system/deliver-pending")
        assert r.status_code == 200
        assert r.json()["delivered"] == 1
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_celery_task_registered():
    from pb_studio.celery_app import celery_app

    assert "pb_studio.worker.deliver_pending_system_notifications" in celery_app.tasks
