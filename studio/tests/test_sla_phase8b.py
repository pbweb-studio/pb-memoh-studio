from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.models import StudioControlGroup
from pb_studio.core.config import Settings, get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.response_queue.service import create_tables
from pb_studio.sla.detector import run_sla_detection_cycle
from pb_studio.sla.models import StudioSlaIncident, StudioSlaPolicy


def _user_raw() -> dict:
    return {"from": {"id": 7, "is_bot": False}, "chat": {"id": 1}}


@pytest_asyncio.fixture
async def b8_engine():
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
async def b8_session(b8_engine):
    factory = async_sessionmaker(b8_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def b8_client(b8_engine):
    factory = async_sessionmaker(b8_engine, class_=AsyncSession, expire_on_commit=False)
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
async def test_muted_policy_skips_new_incident(b8_session: AsyncSession):
    s = Settings(studio_sla_enabled=True, studio_sla_default_first_response_minutes=60)
    now = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
    chat = StudioChat(telegram_chat_id=-7101, chat_type="supergroup", chat_role=ChatRole.CLIENT_CHAT.value)
    b8_session.add(chat)
    await b8_session.flush()
    pol = StudioSlaPolicy(
        chat_role=ChatRole.CLIENT_CHAT.value,
        first_response_minutes=60,
        is_active=True,
        policy_tz="UTC",
        is_muted=True,
    )
    b8_session.add(pol)
    await b8_session.flush()
    m = StudioMessage(
        chat_id=chat.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw_message=_user_raw(),
    )
    b8_session.add(m)
    await b8_session.flush()
    out = await run_sla_detection_cycle(b8_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=now)
    assert out["created"] == 0


@pytest.mark.asyncio
async def test_muted_until_future_skips_then_allows(b8_session: AsyncSession):
    s = Settings(studio_sla_enabled=True, studio_sla_default_first_response_minutes=60)
    t0 = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)
    chat = StudioChat(telegram_chat_id=-7102, chat_type="supergroup", chat_role=ChatRole.CLIENT_CHAT.value)
    b8_session.add(chat)
    await b8_session.flush()
    pol = StudioSlaPolicy(
        chat_role=ChatRole.CLIENT_CHAT.value,
        first_response_minutes=60,
        is_active=True,
        policy_tz="UTC",
        is_muted=False,
        muted_until=t0 + timedelta(hours=5),
    )
    b8_session.add(pol)
    await b8_session.flush()
    m = StudioMessage(
        chat_id=chat.id,
        telegram_message_id=1,
        date=t0 - timedelta(hours=2),
        raw_message=_user_raw(),
    )
    b8_session.add(m)
    await b8_session.flush()
    out1 = await run_sla_detection_cycle(
        b8_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=t0 + timedelta(hours=1)
    )
    assert out1["created"] == 0
    out2 = await run_sla_detection_cycle(
        b8_session, s, send_message=AsyncMock(return_value=(True, 200, "", 1)), now=t0 + timedelta(hours=10)
    )
    assert out2["created"] == 1


@pytest.mark.asyncio
async def test_open_incident_untouched_when_policy_muted(b8_session: AsyncSession):
    s = Settings(
        studio_sla_enabled=True,
        studio_sla_default_first_response_minutes=60,
        telegram_bot_token="123:ABC",
    )
    now = datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc)
    cg_chat = StudioChat(telegram_chat_id=-9201, chat_type="supergroup", chat_role=ChatRole.CONTROL_GROUP.value)
    b8_session.add(cg_chat)
    await b8_session.flush()
    b8_session.add(StudioControlGroup(chat_id=cg_chat.id, is_active=True))
    chat = StudioChat(telegram_chat_id=-7103, chat_type="supergroup", chat_role=ChatRole.CLIENT_CHAT.value)
    b8_session.add(chat)
    await b8_session.flush()
    pol = StudioSlaPolicy(
        chat_role=ChatRole.CLIENT_CHAT.value,
        first_response_minutes=60,
        is_active=True,
        policy_tz="UTC",
        is_muted=True,
    )
    b8_session.add(pol)
    await b8_session.flush()
    trig = StudioMessage(
        chat_id=chat.id,
        telegram_message_id=1,
        date=now - timedelta(hours=2),
        raw_message=_user_raw(),
    )
    b8_session.add(trig)
    await b8_session.flush()
    inc = StudioSlaIncident(
        chat_id=chat.id,
        chat_role=chat.chat_role,
        trigger_message_id=trig.id,
        status="open",
        severity="breached",
        due_at=now - timedelta(hours=1),
        detected_at=now - timedelta(hours=1),
        notification_count=0,
    )
    b8_session.add(inc)
    await b8_session.flush()
    mock = AsyncMock(return_value=(True, 200, "", 1))
    await run_sla_detection_cycle(b8_session, s, send_message=mock, now=now)
    await b8_session.refresh(inc)
    assert inc.status == "open"
    mock.assert_called_once()


@pytest.mark.asyncio
async def test_mute_unmute_patch_api(b8_client):
    client, session = b8_client
    get_settings.cache_clear()
    import os

    os.environ["STUDIO_ADMIN_TOKEN"] = "tok8b"
    get_settings.cache_clear()
    try:
        r = await client.post(
            "/sla/policies",
            headers={"Authorization": "Bearer tok8b"},
            json={"chat_role": "client_chat", "first_response_minutes": 30, "is_active": True, "policy_tz": "UTC"},
        )
        assert r.status_code == 200
        pid = r.json()["id"]
        r2 = await client.post(
            f"/sla/policies/{pid}/mute",
            headers={"Authorization": "Bearer tok8b"},
            json={"mute_reason": "maintenance"},
        )
        assert r2.status_code == 200
        assert r2.json()["is_muted"] is True
        r3 = await client.post(f"/sla/policies/{pid}/unmute", headers={"Authorization": "Bearer tok8b"})
        assert r3.status_code == 200
        assert r3.json()["is_muted"] is False
        r4 = await client.patch(
            f"/sla/policies/{pid}",
            headers={"Authorization": "Bearer tok8b"},
            json={"working_hours_start": "09:00", "working_hours_end": "17:00"},
        )
        assert r4.status_code == 200
        assert r4.json()["working_hours_start"] == "09:00"
    finally:
        import os as _os

        _os.environ.pop("STUDIO_ADMIN_TOKEN", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_api_mute_requires_admin(b8_client):
    client, _ = b8_client
    get_settings.cache_clear()
    import os

    os.environ["STUDIO_ADMIN_TOKEN"] = "x"
    get_settings.cache_clear()
    try:
        r = await client.post("/sla/policies/00000000-0000-0000-0000-000000000001/mute", json={})
        assert r.status_code == 401
    finally:
        import os as _os

        _os.environ.pop("STUDIO_ADMIN_TOKEN", None)
        get_settings.cache_clear()
