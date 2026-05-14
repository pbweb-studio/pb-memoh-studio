from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

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
from pb_studio.response_queue.models import Base
from pb_studio.response_queue.service import create_tables
from pb_studio.sla.constants import SlaIncidentStatus, SlaNotificationEventStatus
from pb_studio.sla.detector import run_sla_detection_cycle
from pb_studio.sla.models import StudioSlaIncident, StudioSlaNotificationEvent
from pb_studio.worker import tasks as worker_tasks


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _user_raw(uid: int = 7) -> dict:
    return {"from": {"id": uid, "is_bot": False, "first_name": "U"}, "chat": {"id": 1}}


def _bot_raw() -> dict:
    return {"from": {"id": 99, "is_bot": True, "first_name": "B"}, "chat": {"id": 1}}


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


@pytest.mark.asyncio
async def test_client_chat_overdue_creates_incident(sla_session: AsyncSession):
    s = Settings(
        studio_sla_enabled=True,
        studio_sla_default_first_response_minutes=60,
        studio_sla_max_notifications_per_incident=3,
    )
    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    chat = await _add_chat(sla_session, telegram_chat_id=-7001, role=ChatRole.CLIENT_CHAT.value)
    u = await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    out = await run_sla_detection_cycle(
        sla_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=now
    )
    assert out["created"] == 1
    inc = await sla_session.scalar(select(StudioSlaIncident))
    assert inc is not None
    assert inc.chat_id == chat.id
    assert inc.trigger_message_id == u.id
    assert inc.status == SlaIncidentStatus.OPEN.value


@pytest.mark.asyncio
async def test_project_chat_overdue_creates_incident(sla_session: AsyncSession):
    s = Settings(
        studio_sla_enabled=True,
        studio_sla_default_first_response_minutes=30,
        studio_sla_max_notifications_per_incident=3,
    )
    now = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)
    chat = await _add_chat(sla_session, telegram_chat_id=-7002, role=ChatRole.PROJECT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=1,
        date=now - timedelta(hours=1),
        raw=_user_raw(),
    )
    out = await run_sla_detection_cycle(sla_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=now)
    assert out["created"] == 1


@pytest.mark.asyncio
async def test_internal_service_control_roles_ignored(sla_session: AsyncSession):
    s = Settings(studio_sla_enabled=True, studio_sla_default_first_response_minutes=1)
    now = datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc)
    for role in (
        ChatRole.INTERNAL_CHAT.value,
        ChatRole.SERVICE_CHAT.value,
        ChatRole.CONTROL_GROUP.value,
        ChatRole.UNKNOWN.value,
    ):
        chat = await _add_chat(sla_session, telegram_chat_id=-8000 - hash(role) % 1000, role=role)
        await _add_msg(
            sla_session,
            chat_id=chat.id,
            telegram_message_id=1,
            date=now - timedelta(days=1),
            raw=_user_raw(),
        )
    out = await run_sla_detection_cycle(sla_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=now)
    assert out["created"] == 0
    n = await sla_session.scalar(select(func.count()).select_from(StudioSlaIncident))
    assert n == 0


@pytest.mark.asyncio
async def test_bot_reply_prevents_or_resolves_incident(sla_session: AsyncSession):
    s = Settings(studio_sla_enabled=True, studio_sla_default_first_response_minutes=60)
    now = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
    chat = await _add_chat(sla_session, telegram_chat_id=-7003, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=2,
        date=now - timedelta(hours=1, minutes=30),
        raw=_bot_raw(),
    )
    out = await run_sla_detection_cycle(sla_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=now)
    assert out["created"] == 0


@pytest.mark.asyncio
async def test_second_run_idempotent_no_duplicate(sla_session: AsyncSession):
    s = Settings(studio_sla_enabled=True, studio_sla_default_first_response_minutes=60)
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    chat = await _add_chat(sla_session, telegram_chat_id=-7004, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    mock = AsyncMock(return_value=(True, 200, "", 1))
    o1 = await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    o2 = await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    assert o1["created"] == 1
    assert o2["created"] == 0
    assert o2["duplicate_skipped"] == 0
    n = await sla_session.scalar(select(func.count()).select_from(StudioSlaIncident))
    assert n == 1


@pytest.mark.asyncio
async def test_no_control_group_no_telegram_call(sla_session: AsyncSession):
    s = Settings(
        studio_sla_enabled=True,
        studio_sla_default_first_response_minutes=60,
        telegram_bot_token="123456:ABC",
    )
    now = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    chat = await _add_chat(sla_session, telegram_chat_id=-7005, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    mock = AsyncMock(return_value=(True, 200, "", 1))
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_with_control_group_notification_target(sla_session: AsyncSession):
    s = Settings(
        studio_sla_enabled=True,
        studio_sla_default_first_response_minutes=60,
        telegram_bot_token="123456:ABC",
    )
    now = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    cg = await _add_chat(sla_session, telegram_chat_id=-9001, role=ChatRole.CONTROL_GROUP.value)
    sla_session.add(StudioControlGroup(chat_id=cg.id, is_active=True))
    client = await _add_chat(sla_session, telegram_chat_id=-7006, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=client.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    mock = AsyncMock(return_value=(True, 200, "", 1))
    await run_sla_detection_cycle(sla_session, s, send_message=mock, now=now)
    mock.assert_called_once()
    kwargs = mock.await_args.kwargs
    assert kwargs["chat_id"] == -9001


@pytest.mark.asyncio
async def test_telegram_error_does_not_raise(sla_session: AsyncSession):
    s = Settings(
        studio_sla_enabled=True,
        studio_sla_default_first_response_minutes=60,
        telegram_bot_token="123456:SECRETTOKEN",
    )
    now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
    cg = await _add_chat(sla_session, telegram_chat_id=-9002, role=ChatRole.CONTROL_GROUP.value)
    sla_session.add(StudioControlGroup(chat_id=cg.id, is_active=True))
    client = await _add_chat(sla_session, telegram_chat_id=-7007, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=client.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    bad = AsyncMock(return_value=(False, 500, "err 123456:SECRETTOKEN", None))
    out = await run_sla_detection_cycle(sla_session, s, send_message=bad, now=now)
    assert out["created"] == 1
    inc = (await sla_session.scalars(select(StudioSlaIncident))).first()
    assert inc is not None
    assert inc.last_error is not None
    assert "SECRETTOKEN" not in (inc.last_error or "")
    assert "***BOT_TOKEN***" in (inc.last_error or "")
    ev = await sla_session.scalar(
        select(StudioSlaNotificationEvent).where(StudioSlaNotificationEvent.incident_id == inc.id)
    )
    assert ev is not None
    assert ev.status == SlaNotificationEventStatus.FAILED.value
    assert ev.error is not None
    assert "SECRETTOKEN" not in ev.error


@pytest.mark.asyncio
async def test_api_requires_admin_token(sla_client):
    client, _ = sla_client
    get_settings.cache_clear()
    import os

    os.environ["STUDIO_ADMIN_TOKEN"] = "secret-admin"
    get_settings.cache_clear()
    try:
        r = await client.get("/sla/incidents")
        assert r.status_code == 401
        r2 = await client.get("/sla/incidents", headers={"Authorization": "Bearer secret-admin"})
        assert r2.status_code == 200
    finally:
        import os as _os

        _os.environ.pop("STUDIO_ADMIN_TOKEN", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_api_ack_resolve(sla_client):
    client, session = sla_client
    get_settings.cache_clear()
    import os

    os.environ["STUDIO_ADMIN_TOKEN"] = "adm"
    get_settings.cache_clear()
    try:
        now = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)
        chat = await _add_chat(session, telegram_chat_id=-7010, role=ChatRole.CLIENT_CHAT.value)
        trig = await _add_msg(
            session,
            chat_id=chat.id,
            telegram_message_id=1,
            date=now - timedelta(hours=2),
            raw=_user_raw(),
        )
        inc = StudioSlaIncident(
            chat_id=chat.id,
            chat_role=chat.chat_role,
            trigger_message_id=trig.id,
            status=SlaIncidentStatus.OPEN.value,
            severity="breached",
            due_at=now - timedelta(hours=1),
            detected_at=now,
            notification_count=0,
        )
        session.add(inc)
        await session.commit()

        r = await client.post(f"/sla/incidents/{inc.id}/ack", headers={"Authorization": "Bearer adm"})
        assert r.status_code == 200
        assert r.json()["status"] == SlaIncidentStatus.ACKNOWLEDGED.value

        r2 = await client.post(f"/sla/incidents/{inc.id}/resolve", headers={"Authorization": "Bearer adm"})
        assert r2.status_code == 200
        assert r2.json()["status"] == SlaIncidentStatus.RESOLVED.value
    finally:
        import os as _os

        _os.environ.pop("STUDIO_ADMIN_TOKEN", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_open_incident_resolved_after_bot_reply(sla_session: AsyncSession):
    s = Settings(studio_sla_enabled=True, studio_sla_default_first_response_minutes=60)
    t0 = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)
    now1 = datetime(2026, 3, 11, 13, 0, tzinfo=timezone.utc)
    chat = await _add_chat(sla_session, telegram_chat_id=-7020, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=1,
        date=t0,
        raw=_user_raw(),
    )
    o1 = await run_sla_detection_cycle(
        sla_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=now1
    )
    assert o1["created"] == 1
    await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=2,
        date=now1 + timedelta(minutes=1),
        raw=_bot_raw(),
    )
    now2 = now1 + timedelta(hours=1)
    o2 = await run_sla_detection_cycle(
        sla_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=now2
    )
    assert o2["resolved_answered"] >= 1
    inc = (await sla_session.scalars(select(StudioSlaIncident))).first()
    assert inc.status == SlaIncidentStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_post_policy_via_api(sla_client):
    client, _session = sla_client
    get_settings.cache_clear()
    import os

    os.environ["STUDIO_ADMIN_TOKEN"] = "adm2"
    get_settings.cache_clear()
    try:
        r = await client.post(
            "/sla/policies",
            headers={"Authorization": "Bearer adm2"},
            json={
                "chat_role": "client_chat",
                "first_response_minutes": 45,
                "followup_minutes": 120,
                "is_active": True,
            },
        )
        assert r.status_code == 200
        assert r.json()["first_response_minutes"] == 45
        r2 = await client.get("/sla/policies", headers={"Authorization": "Bearer adm2"})
        assert r2.status_code == 200
        assert len(r2.json()) >= 1
    finally:
        import os as _os

        _os.environ.pop("STUDIO_ADMIN_TOKEN", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_celery_task_import_and_name():
    assert worker_tasks.detect_sla_incidents.name == "pb_studio.worker.detect_sla_incidents"
    assert callable(worker_tasks.detect_sla_incidents)


@pytest.mark.asyncio
async def test_no_httpx_when_send_injected(monkeypatch, sla_session):
    calls: list[str] = []

    async def guard(*_a, **_k):
        calls.append("httpx")
        raise AssertionError("httpx must not be used")

    monkeypatch.setattr(httpx, "AsyncClient", guard)
    s = Settings(studio_sla_enabled=True, studio_sla_default_first_response_minutes=60)
    now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    chat = await _add_chat(sla_session, telegram_chat_id=-7011, role=ChatRole.CLIENT_CHAT.value)
    await _add_msg(
        sla_session,
        chat_id=chat.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw=_user_raw(),
    )
    await run_sla_detection_cycle(
        sla_session,
        s,
        send_message=AsyncMock(return_value=(True, 200, "", 1)),
        now=now,
    )
    assert calls == []
