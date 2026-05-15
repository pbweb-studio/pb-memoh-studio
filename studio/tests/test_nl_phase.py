from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_group.constants import ChatRole
from pb_studio.core.config import Settings, get_settings
from pb_studio.event_mirror.models import StudioChat
from pb_studio.nl.models import StudioNlInteraction
from pb_studio.nl.router_deterministic import route_deterministic
from pb_studio.nl.schemas import IntentEnum, RouterModeEnum
from pb_studio.nl.triggers import strip_alias_prefix
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def nl_engine():
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
async def nl_client(nl_engine):
    factory = async_sessionmaker(nl_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env_nl(monkeypatch: pytest.MonkeyPatch, *, nl_on: bool = True) -> None:
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true" if nl_on else "false")
    monkeypatch.setenv("STUDIO_NL_ROUTER_PROVIDER", "deterministic")
    get_settings.cache_clear()


def test_route_deterministic_digest_and_help():
    d1 = route_deterministic("дай сводку за сегодня")
    assert d1.intent == IntentEnum.studio_digest
    assert d1.mode == RouterModeEnum.business_action
    d2 = route_deterministic("что ты умеешь")
    assert d2.intent == IntentEnum.help_capabilities


def test_strip_alias_prefix_jarvis():
    s = Settings()
    rest, ok = strip_alias_prefix("Jarvis, покажи риски", s)
    assert ok is True
    assert "риск" in rest.lower()


@pytest.mark.asyncio
async def test_nl_gate_disabled_returns_403(nl_client, monkeypatch):
    _env_nl(monkeypatch, nl_on=False)
    client, _session = nl_client
    r = await client.post(
        "/integrations/memoh/nl-gate",
        json={
            "telegram_chat_id": -1,
            "message_id": 1,
            "text": "hello @bot",
            "raw_text": "hello @bot",
            "is_mentioned": True,
            "is_bot": False,
        },
    )
    assert r.status_code == 403
    assert "STUDIO_NL_COMMANDS_ENABLED" in (r.json().get("detail") or "")


@pytest.mark.asyncio
async def test_nl_gate_suppress_mention_and_idempotent(nl_client, monkeypatch):
    _env_nl(monkeypatch, nl_on=True)
    client, session = nl_client
    chat_id = -88001
    await client.post("/events/telegram", json=_tg_msg(1, chat_id))
    await client.post("/control-group/set", json={"telegram_chat_id": chat_id})

    cg = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == chat_id))
    assert cg is not None
    assert cg.chat_role == ChatRole.CONTROL_GROUP.value

    body = {
        "telegram_chat_id": chat_id,
        "message_id": 99,
        "update_id": 5001,
        "text": "что нового",
        "raw_text": "что нового",
        "from_id": 4242,
        "is_mentioned": True,
        "is_reply_to_bot": False,
        "is_bot": False,
    }
    r1 = await client.post("/integrations/memoh/nl-gate", json=body)
    assert r1.status_code == 200
    assert r1.json()["suppress_memoh_assistant"] is True

    n = await session.scalar(select(func.count()).select_from(StudioNlInteraction))
    assert n == 1

    r2 = await client.post("/integrations/memoh/nl-gate", json=body)
    assert r2.status_code == 200
    assert r2.json()["suppress_memoh_assistant"] is True
    assert r2.json()["reason"] == "already_enqueued"

    n2 = await session.scalar(select(func.count()).select_from(StudioNlInteraction))
    assert n2 == 1


@pytest.mark.asyncio
async def test_nl_gate_studio_slash_not_suppressed(nl_client, monkeypatch):
    _env_nl(monkeypatch, nl_on=True)
    client, session = nl_client
    chat_id = -88002
    await client.post("/events/telegram", json=_tg_msg(1, chat_id))
    await client.post("/control-group/set", json={"telegram_chat_id": chat_id})

    r = await client.post(
        "/integrations/memoh/nl-gate",
        json={
            "telegram_chat_id": chat_id,
            "message_id": 10,
            "text": "/summary_today",
            "raw_text": "/summary_today",
            "from_id": 1,
            "is_mentioned": True,
            "is_bot": False,
        },
    )
    assert r.status_code == 200
    assert r.json()["suppress_memoh_assistant"] is False
    n = await session.scalar(select(func.count()).select_from(StudioNlInteraction))
    assert n == 0


def _tg_msg(update_id: int, chat_id: int) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "CG"},
            "from": {"id": 42, "is_bot": False, "first_name": "U"},
            "text": "hello",
        },
    }
