from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.models import StudioControlGroup
from pb_studio.core.config import Settings, get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.response_queue.service import create_tables
from pb_studio.sla.constants import SlaIncidentStatus, SlaNotificationEventStatus
from pb_studio.sla.detector import run_sla_detection_cycle
from pb_studio.sla.models import StudioSlaIncident, StudioSlaNotificationEvent


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _user_raw(uid: int = 7) -> dict:
    return {"from": {"id": uid, "is_bot": False, "first_name": "U"}, "chat": {"id": 1}}


async def _add_chat(session: AsyncSession, *, telegram_chat_id: int, role: str) -> StudioChat:
    c = StudioChat(telegram_chat_id=telegram_chat_id, chat_type="supergroup", chat_role=role, title="T")
    session.add(c)
    await session.flush()
    return c


async def _add_msg(
    session: AsyncSession,
    *,
    chat_id,
    telegram_message_id: int,
    date: datetime,
    raw: dict,
) -> StudioMessage:
    m = StudioMessage(
        chat_id=chat_id,
        telegram_message_id=telegram_message_id,
        date=_utc(date),
        raw_message=raw,
    )
    session.add(m)
    await session.flush()
    return m


@pytest_asyncio.fixture
async def sla_engine():
    import pb_studio.control_group.models  # noqa: F401
    import pb_studio.control_commands.models  # noqa: F401
    import pb_studio.event_mirror.models  # noqa: F401
    import pb_studio.summaries.models  # noqa: F401
    import pb_studio.sla.models  # noqa: F401

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await create_tables(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sla_session(sla_engine):
    factory = async_sessionmaker(sla_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def sla_client(sla_engine):
    factory = async_sessionmaker(sla_engine, class_=AsyncSession, expire_on_commit=False)
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


def _base_settings(**kwargs) -> Settings:
    defaults = dict(
        studio_sla_enabled=True,
        studio_sla_default_first_response_minutes=60,
        studio_sla_max_notifications_per_incident=3,
        studio_sla_notification_cooldown_minutes=30,
        studio_sla_notification_digest_max_items=10,
        studio_sla_notification_text_max_len=3500,
        telegram_bot_token="123456:ABC",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


async def _setup_cg_and_client(session: AsyncSession, *, now: datetime, client_tg: int = -7101):
    cg = await _add_chat(session, telegram_chat_id=-9001, role=ChatRole.CONTROL_GROUP.value)
    session.add(StudioControlGroup(chat_id=cg.id, is_active=True))
    client = await _add_chat(session, telegram_chat_id=client_tg, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        session,
        chat_id=client.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    return client


@pytest.mark.asyncio
async def test_first_sla_notification_sent_and_event(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    await _setup_cg_and_client(sla_session, now=now)
    mock = AsyncMock(return_value=(True, 200, "", 42))
    s = _base_settings()
    out = await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    assert out["sla_notify_sent"] == 1
    mock.assert_called_once()
    inc = (await sla_session.scalars(select(StudioSlaIncident))).first()
    assert inc is not None
    assert inc.notification_count == 1
    assert inc.next_notification_at is not None
    ev = (await sla_session.scalars(select(StudioSlaNotificationEvent))).first()
    assert ev is not None
    assert ev.status == SlaNotificationEventStatus.SENT.value
    assert ev.telegram_message_id == 42


@pytest.mark.asyncio
async def test_repeat_before_cooldown_suppressed_no_telegram(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    await _setup_cg_and_client(sla_session, now=now)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _base_settings(studio_sla_notification_cooldown_minutes=60)
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    mock.reset_mock()
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now + timedelta(minutes=5))
    mock.assert_not_called()
    sup = await sla_session.scalar(
        select(func.count()).select_from(StudioSlaNotificationEvent).where(
            StudioSlaNotificationEvent.status == SlaNotificationEventStatus.SUPPRESSED.value,
            StudioSlaNotificationEvent.reason == "cooldown",
        )
    )
    assert int(sup or 0) >= 1


@pytest.mark.asyncio
async def test_after_cooldown_second_notification(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    await _setup_cg_and_client(sla_session, now=now)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _base_settings(studio_sla_notification_cooldown_minutes=10)
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    mock.reset_mock()
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now + timedelta(minutes=11))
    mock.assert_called_once()
    inc = (await sla_session.scalars(select(StudioSlaIncident))).first()
    assert inc.notification_count == 2


@pytest.mark.asyncio
async def test_max_notifications_suppresses(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    await _setup_cg_and_client(sla_session, now=now)
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _base_settings(
        studio_sla_max_notifications_per_incident=2,
        studio_sla_notification_cooldown_minutes=1,
    )
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now + timedelta(minutes=2))
    mock.reset_mock()
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now + timedelta(minutes=4))
    mock.assert_not_called()
    inc = (await sla_session.scalars(select(StudioSlaIncident))).first()
    assert inc.notification_count == 2
    sup = await sla_session.scalar(
        select(func.count()).select_from(StudioSlaNotificationEvent).where(
            StudioSlaNotificationEvent.status == SlaNotificationEventStatus.SUPPRESSED.value,
            StudioSlaNotificationEvent.reason == "max_notifications",
        )
    )
    assert int(sup or 0) >= 1


@pytest.mark.asyncio
async def test_telegram_exception_writes_failed_event(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    await _setup_cg_and_client(sla_session, now=now)
    bad = AsyncMock(side_effect=TimeoutError("network 123456:ABC"))
    s = _base_settings(telegram_bot_token="123456:ABC")
    await run_sla_detection_cycle(sla_session, s, send_message=bad, now=now)
    ev = (await sla_session.scalars(select(StudioSlaNotificationEvent))).first()
    assert ev is not None
    assert ev.status == SlaNotificationEventStatus.FAILED.value
    assert ev.error is not None
    assert "ABC" not in ev.error


@pytest.mark.asyncio
async def test_digest_single_send_message_for_two_incidents(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    cg = await _add_chat(sla_session, telegram_chat_id=-9001, role=ChatRole.CONTROL_GROUP.value)
    sla_session.add(StudioControlGroup(chat_id=cg.id, is_active=True))
    c1 = await _add_chat(sla_session, telegram_chat_id=-7101, role=ChatRole.CLIENT_CHAT.value)
    c2 = await _add_chat(sla_session, telegram_chat_id=-7102, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(sla_session, chat_id=c1.id, telegram_message_id=1, date=now - timedelta(hours=2), raw=_user_raw())
    await _add_msg(sla_session, chat_id=c2.id, telegram_message_id=1, date=now - timedelta(hours=2), raw=_user_raw(uid=8))
    mock = AsyncMock(return_value=(True, 200, "", 99))
    s = _base_settings()
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    mock.assert_called_once()
    kwargs = mock.await_args.kwargs
    assert "digest" in kwargs["text"].lower() or "SLA digest" in kwargs["text"]
    n = await sla_session.scalar(select(func.count()).select_from(StudioSlaIncident))
    assert n == 2


@pytest.mark.asyncio
async def test_digest_truncation_safe(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    cg = await _add_chat(sla_session, telegram_chat_id=-9001, role=ChatRole.CONTROL_GROUP.value)
    sla_session.add(StudioControlGroup(chat_id=cg.id, is_active=True))
    for idx in range(2):
        ch = await _add_chat(sla_session, telegram_chat_id=-7200 - idx, role=ChatRole.CLIENT_CHAT.value)
        await _add_msg(
            sla_session,
            chat_id=ch.id,
            telegram_message_id=1,
            date=now - timedelta(hours=2),
            raw=_user_raw(uid=10 + idx),
        )
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _base_settings(studio_sla_notification_text_max_len=120)
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    text = mock.await_args.kwargs["text"]
    assert len(text) <= 120


@pytest.mark.asyncio
async def test_no_control_group_no_send_message(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    ch = await _add_chat(sla_session, telegram_chat_id=-7105, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=ch.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = _base_settings()
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    mock.assert_not_called()
    inc = (await sla_session.scalars(select(StudioSlaIncident))).first()
    assert inc is not None


@pytest.mark.asyncio
async def test_notification_events_api_requires_admin(sla_client):
    client, _ = sla_client
    get_settings.cache_clear()
    import os

    os.environ["STUDIO_ADMIN_TOKEN"] = "adm8c"
    get_settings.cache_clear()
    try:
        r = await client.get("/sla/notification-events")
        assert r.status_code == 401
        r2 = await client.get("/sla/notification-events", headers={"Authorization": "Bearer adm8c"})
        assert r2.status_code == 200
    finally:
        import os as _os

        _os.environ.pop("STUDIO_ADMIN_TOKEN", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_manual_notify_endpoint(sla_client):
    client, session = sla_client
    get_settings.cache_clear()
    import os

    os.environ["STUDIO_ADMIN_TOKEN"] = "adm8c2"
    os.environ["TELEGRAM_BOT_TOKEN"] = "888:TESTTOKEN"
    get_settings.cache_clear()
    try:
        now = datetime(2026, 5, 14, 15, 0, tzinfo=timezone.utc)
        cg = await _add_chat(session, telegram_chat_id=-9002, role=ChatRole.CONTROL_GROUP.value)
        session.add(StudioControlGroup(chat_id=cg.id, is_active=True))
        ch = await _add_chat(session, telegram_chat_id=-7110, role=ChatRole.CLIENT_CHAT.value)
        trig = await _add_msg(
            session,
            chat_id=ch.id,
            telegram_message_id=1,
            date=now - timedelta(hours=2),
            raw=_user_raw(),
        )
        inc = StudioSlaIncident(
            chat_id=ch.id,
            chat_role=ch.chat_role,
            trigger_message_id=trig.id,
            status=SlaIncidentStatus.OPEN.value,
            severity="breached",
            due_at=now - timedelta(hours=1),
            detected_at=now,
            notification_count=0,
        )
        session.add(inc)
        await session.commit()

        from unittest.mock import patch

        with patch("pb_studio.sla.service.telegram_send_message", new=AsyncMock(return_value=(True, 200, "", 5))):
            get_settings.cache_clear()
            r = await client.post(
                f"/sla/incidents/{inc.id}/notify",
                headers={"Authorization": "Bearer adm8c2"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        assert body.get("sla_notify_sent", 0) >= 1
    finally:
        import os as _os

        _os.environ.pop("STUDIO_ADMIN_TOKEN", None)
        _os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_no_httpx_when_send_injected(monkeypatch, sla_session):
    calls: list[str] = []

    async def guard(*_a, **_k):
        calls.append("httpx")
        raise AssertionError("httpx must not be used")

    monkeypatch.setattr(httpx, "AsyncClient", guard)
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    await _setup_cg_and_client(sla_session, now=now)
    await run_sla_detection_cycle(
        sla_session,
        _base_settings(),
        send_message=AsyncMock(return_value=(True, 200, "", 1)),
        now=now,
    )
    assert calls == []


@pytest.mark.asyncio
async def test_payload_json_no_bot_token(sla_session: AsyncSession):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    await _setup_cg_and_client(sla_session, now=now)
    tok = "777777:ZZZSECRET"
    s = _base_settings(telegram_bot_token=tok)
    await run_sla_detection_cycle(
        sla_session,
        s,
        send_message=AsyncMock(return_value=(True, 200, "", 1)),
        now=now,
    )
    ev = (await sla_session.scalars(select(StudioSlaNotificationEvent))).first()
    assert ev is not None
    dumped = str(ev.payload_json or {})
    assert "ZZZSECRET" not in dumped