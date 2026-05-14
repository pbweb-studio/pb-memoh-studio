from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.celery_app import celery_app
from pb_studio.control_group.constants import ChatRole
from pb_studio.core.config import Settings, get_settings
from pb_studio.event_mirror.models import AuditLog, StudioChat
from pb_studio.response_queue.models import Base
from pb_studio.summaries.constants import SummaryDeliveryStatus, SummaryStatus, SummaryType
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.summary_delivery import (
    deliver_pending_summaries_batch,
    deliver_summary_to_control_group_by_id,
    try_deliver_summary_row,
)
from pb_studio.worker.tasks import deliver_pending_chat_summaries


@pytest_asyncio.fixture
async def d6_engine():
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
async def d6_client(d6_engine):
    factory = async_sessionmaker(d6_engine, class_=AsyncSession, expire_on_commit=False)
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


def _msg(update_id: int, chat_id: int) -> dict:
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


def _delivery_settings(**kwargs: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://x:x@127.0.0.1:9/x",
        "redis_url": "redis://127.0.0.1:9/0",
        "celery_broker_url": "redis://127.0.0.1:9/1",
        "studio_summary_delivery_enabled": True,
        "telegram_bot_token": "BOT_SECRET_XYZ",
        "studio_summary_delivery_max_retries": 3,
        "studio_telegram_send_timeout_ms": 3000,
    }
    base.update(kwargs)
    return Settings.model_validate(base)


def _period():
    p0 = datetime(2026, 1, 10, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    return p0, p1


async def _add_generated_summary(
    session: AsyncSession,
    *,
    source_telegram_chat_id: int,
    delivery_status: str = SummaryDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY,
) -> StudioChatSummary:
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == source_telegram_chat_id))
    p0, p1 = _period()
    row = StudioChatSummary(
        chat_id=chat.id,
        chat_role=ChatRole.CLIENT_CHAT.value,
        summary_type=SummaryType.MANUAL,
        period_start=p0,
        period_end=p1,
        status=SummaryStatus.GENERATED,
        source_event_count=1,
        summary_text="LINE_FOR_SUMMARY",
        delivery_status=delivery_status,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_deliver_success_to_control_group(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96001, chat_id=-96001))
    await client.post("/events/telegram", json=_msg(96002, chat_id=-96002))
    await client.post("/control-group/set", json={"telegram_chat_id": -96002})
    row = await _add_generated_summary(session, source_telegram_chat_id=-96001)
    mock = AsyncMock(return_value=(True, 200, "", 4242))
    s = _delivery_settings()
    await try_deliver_summary_row(session, row, s, send_message=mock)
    await session.commit()
    assert row.delivery_status == SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP
    assert row.telegram_message_id == 4242
    mock.assert_awaited_once()
    assert mock.await_args.kwargs["chat_id"] == -96002
    assert "LINE_FOR_SUMMARY" in mock.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_no_control_group_does_not_send_keeps_pending(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96003, chat_id=-96003))
    row = await _add_generated_summary(session, source_telegram_chat_id=-96003)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _delivery_settings()
    out = await try_deliver_summary_row(session, row, s, send_message=mock)
    await session.commit()
    assert out == "waiting_no_control_group"
    assert row.delivery_status == SummaryDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY
    assert "no active control group" in (row.delivery_last_error or "")
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_destination_wrong_role_blocks_no_send(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96004, chat_id=-96004))
    await client.post("/control-group/set", json={"telegram_chat_id": -96004})
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -96004))
    chat.chat_role = ChatRole.CLIENT_CHAT.value
    await session.commit()
    await client.post("/events/telegram", json=_msg(96005, chat_id=-96005))
    row = await _add_generated_summary(session, source_telegram_chat_id=-96005)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _delivery_settings()
    out = await try_deliver_summary_row(session, row, s, send_message=mock)
    await session.commit()
    assert out == "failed_permanent_config"
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_200_delivered(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96006, chat_id=-96006))
    await client.post("/events/telegram", json=_msg(96007, chat_id=-96007))
    await client.post("/control-group/set", json={"telegram_chat_id": -96007})
    row = await _add_generated_summary(session, source_telegram_chat_id=-96006)
    mock = AsyncMock(return_value=(True, 200, "", 77))
    s = _delivery_settings()
    await try_deliver_summary_row(session, row, s, send_message=mock)
    await session.commit()
    assert row.delivery_status == SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP
    assert row.delivered_at is not None


@pytest.mark.asyncio
async def test_telegram_500_retryable_then_permanent(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96008, chat_id=-96008))
    await client.post("/events/telegram", json=_msg(96009, chat_id=-96009))
    await client.post("/control-group/set", json={"telegram_chat_id": -96009})
    row = await _add_generated_summary(session, source_telegram_chat_id=-96008)
    mock = AsyncMock(return_value=(False, 500, "boom", None))
    s = _delivery_settings(studio_summary_delivery_max_retries=2)
    await try_deliver_summary_row(session, row, s, send_message=mock)
    await session.commit()
    assert row.delivery_status == SummaryDeliveryStatus.FAILED_RETRYABLE
    assert row.delivery_retry_count == 1
    await try_deliver_summary_row(session, row, s, send_message=mock)
    await session.commit()
    assert row.delivery_status == SummaryDeliveryStatus.FAILED_PERMANENT
    assert row.delivery_retry_count == 2


@pytest.mark.asyncio
async def test_batch_idempotent_delivered_not_resent(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96010, chat_id=-96010))
    await client.post("/events/telegram", json=_msg(96011, chat_id=-96011))
    await client.post("/control-group/set", json={"telegram_chat_id": -96011})
    row = await _add_generated_summary(session, source_telegram_chat_id=-96010)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _delivery_settings()
    c1 = await deliver_pending_summaries_batch(session, s, send_message=mock)
    await session.commit()
    assert c1["delivered"] == 1
    c2 = await deliver_pending_summaries_batch(session, s, send_message=mock)
    await session.commit()
    assert c2["delivered"] == 0
    assert c2["examined"] == 0
    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_api_requires_admin(d6_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm6d")
    get_settings.cache_clear()
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96012, chat_id=-96012))
    row = await _add_generated_summary(session, source_telegram_chat_id=-96012)
    r = await client.post(f"/summaries/{row.id}/deliver-control-group")
    assert r.status_code == 401
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_api_deliver_and_filter(d6_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm6d")
    monkeypatch.setenv("STUDIO_SUMMARY_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "BOT_SECRET_XYZ")
    get_settings.cache_clear()
    client, session = d6_client
    hdr = {"Authorization": "Bearer adm6d"}
    await client.post("/events/telegram", json=_msg(96013, chat_id=-96013))
    await client.post("/events/telegram", json=_msg(96014, chat_id=-96014))
    cg = await client.post(
        "/control-group/set",
        json={"telegram_chat_id": -96014},
        headers=hdr,
    )
    assert cg.status_code == 200, cg.text
    row = await _add_generated_summary(session, source_telegram_chat_id=-96013)

    ok = AsyncMock(return_value=(True, 200, "", 9001))
    monkeypatch.setattr("pb_studio.summaries.summary_delivery.telegram_send_message", ok)
    r = await client.post(f"/summaries/{row.id}/deliver-control-group", headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["delivery_status"] == SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP
    r2 = await client.post(f"/summaries/{row.id}/deliver-control-group", headers=hdr)
    assert r2.json().get("reason") == "already_delivered"
    rlist = await client.get(
        "/summaries",
        headers=hdr,
        params={"delivery_status": SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP},
    )
    assert rlist.status_code == 200
    ids = {x["id"] for x in rlist.json()}
    assert str(row.id) in ids
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_token_redacted_in_delivery_error_and_audit(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96015, chat_id=-96015))
    await client.post("/events/telegram", json=_msg(96016, chat_id=-96016))
    await client.post("/control-group/set", json={"telegram_chat_id": -96016})
    row = await _add_generated_summary(session, source_telegram_chat_id=-96015)

    async def bad_send(*, bot_token: str, **kwargs: object) -> tuple[bool, int | None, str, int | None]:
        return False, 400, f"err {bot_token} x", None

    s = _delivery_settings(telegram_bot_token="BOT_SECRET_XYZ")
    await try_deliver_summary_row(session, row, s, send_message=bad_send)
    await session.commit()
    assert "BOT_SECRET_XYZ" not in (row.delivery_last_error or "")
    assert "***BOT_TOKEN***" in (row.delivery_last_error or "")
    logs = (await session.scalars(select(AuditLog))).all()
    blob = " ".join(str(getattr(l, "payload", None)) for l in logs)
    assert "BOT_SECRET_XYZ" not in blob


@pytest.mark.asyncio
async def test_refused_when_source_chat_is_control_group_destination(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96017, chat_id=-96017))
    await client.post("/control-group/set", json={"telegram_chat_id": -96017})
    row = await _add_generated_summary(session, source_telegram_chat_id=-96017)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _delivery_settings()
    out = await try_deliver_summary_row(session, row, s, send_message=mock)
    await session.commit()
    assert out == "refused_source_equals_dest"
    mock.assert_not_called()


def test_celery_deliver_task_registered():
    assert "pb_studio.worker.deliver_pending_chat_summaries" in celery_app.tasks
    assert deliver_pending_chat_summaries.name == "pb_studio.worker.deliver_pending_chat_summaries"


@pytest.mark.asyncio
async def test_deliver_by_id_raises_when_not_generated(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96018, chat_id=-96018))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -96018))
    p0, p1 = _period()
    row = StudioChatSummary(
        chat_id=chat.id,
        chat_role=ChatRole.CLIENT_CHAT.value,
        summary_type=SummaryType.MANUAL,
        period_start=p0,
        period_end=p1,
        status=SummaryStatus.PENDING,
        source_event_count=0,
        summary_text=None,
        delivery_status=SummaryDeliveryStatus.NOT_REQUESTED,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    s = _delivery_settings()
    with pytest.raises(ValueError, match="generated"):
        await deliver_summary_to_control_group_by_id(session, row.id, s)


@pytest.mark.asyncio
async def test_deliver_pending_disabled_counts(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96019, chat_id=-96019))
    row = await _add_generated_summary(session, source_telegram_chat_id=-96019)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _delivery_settings(studio_summary_delivery_enabled=False)
    c = await deliver_pending_summaries_batch(session, s, send_message=mock)
    assert c["skipped_disabled"] == 1
    mock.assert_not_called()
    await session.refresh(row)
    assert row.delivery_status == SummaryDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY


@pytest.mark.asyncio
async def test_post_deliver_pending_endpoint(d6_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm6d2")
    monkeypatch.setenv("STUDIO_SUMMARY_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "BOT_SECRET_XYZ")
    get_settings.cache_clear()
    client, session = d6_client
    hdr = {"Authorization": "Bearer adm6d2"}
    await client.post("/events/telegram", json=_msg(96020, chat_id=-96020))
    await client.post("/events/telegram", json=_msg(96021, chat_id=-96021))
    await client.post(
        "/control-group/set",
        json={"telegram_chat_id": -96021},
        headers=hdr,
    )
    await _add_generated_summary(session, source_telegram_chat_id=-96020)

    ok = AsyncMock(return_value=(True, 200, "", 333))
    monkeypatch.setattr("pb_studio.summaries.summary_delivery.telegram_send_message", ok)
    r = await client.post("/summaries/deliver-pending", headers=hdr)
    assert r.status_code == 200
    assert r.json()["delivered"] >= 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_delivery_uses_injected_sender_only(d6_client):
    client, session = d6_client
    await client.post("/events/telegram", json=_msg(96022, chat_id=-96022))
    await client.post("/events/telegram", json=_msg(96023, chat_id=-96023))
    await client.post("/control-group/set", json={"telegram_chat_id": -96023})
    row = await _add_generated_summary(session, source_telegram_chat_id=-96022)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _delivery_settings()
    await try_deliver_summary_row(session, row, s, send_message=mock)
    mock.assert_awaited_once()
