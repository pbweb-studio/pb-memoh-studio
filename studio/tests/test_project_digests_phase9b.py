from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pb_studio.control_commands.models  # noqa: F401
import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.project_digests.models  # noqa: F401
import pb_studio.projects.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.celery_app import celery_app
from pb_studio.control_commands.constants import ControlCommandName, ControlCommandStatus
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.control_commands.service import run_control_commands_cycle
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.project_digests.constants import ProjectDigestStatus
from pb_studio.project_digests.delivery import try_deliver_project_digest_row
from pb_studio.project_digests.models import StudioProjectDigest
from pb_studio.response_queue.models import Base
from pb_studio.summaries.constants import SummaryStatus, SummaryType
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.planner import utc_day_bounds


@pytest_asyncio.fixture
async def d9_engine():
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
async def d9_client(d9_engine):
    factory = async_sessionmaker(d9_engine, class_=AsyncSession, expire_on_commit=False)
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


def _msg(
    update_id: int,
    chat_id: int,
    *,
    text: str = "hello",
    message_id: int = 1,
    from_user_id: int = 42,
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "T"},
            "from": {"id": from_user_id, "is_bot": False, "first_name": "U"},
            "text": text,
        },
    }


def _env_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    monkeypatch.setenv("STUDIO_SUMMARY_DELIVERY_ENABLED", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_project_digest_today_generated_and_idempotent(d9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9b")
    _env_digest(monkeypatch)
    fixed = datetime(2025, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    monkeypatch.setattr("pb_studio.project_digests.service.summaries_clock", lambda: fixed)

    client, session = d9_client
    headers = {"Authorization": "Bearer adm9b"}
    await client.post("/projects", headers=headers, json={"slug": "dig", "name": "Dig"})
    lst = await client.get("/projects", headers=headers)
    pid = lst.json()[0]["id"]

    await client.post("/events/telegram", json=_msg(880001, -88001))
    await client.post(
        "/control-group/set",
        headers=headers,
        json={"telegram_chat_id": -88001},
    )
    await client.post("/events/telegram", json=_msg(880002, -88002))
    ch = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -88002))
    assert ch is not None
    p0, _p1 = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=ch.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=3),
            text="digest seed",
            raw_message={"from": {"id": 9, "is_bot": False}, "text": "digest seed"},
        )
    )
    await session.commit()

    await client.post(
        f"/projects/{pid}/bind-chat",
        headers=headers,
        json={"chat_id": str(ch.id), "role_in_project": "secondary"},
    )

    r1 = await client.post(f"/projects/{pid}/digests/today", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["status"] == ProjectDigestStatus.GENERATED
    d1 = r1.json()["id"]
    r2 = await client.post(f"/projects/{pid}/digests/today", headers=headers)
    assert r2.json()["id"] == d1
    n = await session.scalar(select(func.count()).select_from(StudioProjectDigest))
    assert n == 1


@pytest.mark.asyncio
async def test_project_digest_no_active_chats_message(d9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9b")
    _env_digest(monkeypatch)
    fixed = datetime(2025, 6, 11, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    monkeypatch.setattr("pb_studio.project_digests.service.summaries_clock", lambda: fixed)

    client, session = d9_client
    headers = {"Authorization": "Bearer adm9b"}
    await client.post("/projects", headers=headers, json={"slug": "solo", "name": "Solo"})
    pid = (await client.get("/projects", headers=headers)).json()[0]["id"]
    r = await client.post(f"/projects/{pid}/digests/today", headers=headers)
    assert r.status_code == 200
    assert "нет активных чатов" in (r.json().get("digest_text") or "").lower()


@pytest.mark.asyncio
async def test_digest_failed_summary_recorded_not_fatal(d9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9b")
    _env_digest(monkeypatch)
    fixed = datetime(2025, 6, 12, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    monkeypatch.setattr("pb_studio.project_digests.service.summaries_clock", lambda: fixed)

    client, session = d9_client
    headers = {"Authorization": "Bearer adm9b"}
    await client.post("/projects", headers=headers, json={"slug": "badsum", "name": "Bad"})
    pid = (await client.get("/projects", headers=headers)).json()[0]["id"]
    await client.post("/events/telegram", json=_msg(881001, -88101))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -88101})
    await client.post("/events/telegram", json=_msg(881002, -88102))
    ch = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -88102))
    await client.post(
        f"/projects/{pid}/bind-chat",
        headers=headers,
        json={"chat_id": str(ch.id), "role_in_project": "secondary"},
    )
    p0, p1 = utc_day_bounds(fixed.date())
    session.add(
        StudioChatSummary(
            chat_id=ch.id,
            chat_role=ch.chat_role,
            summary_type=SummaryType.DAILY,
            period_start=p0,
            period_end=p1,
            status=SummaryStatus.FAILED,
            source_event_count=0,
            summary_text=None,
            last_error="boom",
        )
    )
    await session.commit()

    r = await client.post(f"/projects/{pid}/digests/today", headers=headers)
    assert r.status_code == 200
    meta = r.json().get("metadata_json") or {}
    chats = meta.get("chat_summaries") or []
    assert any(c.get("outcome") == "failed_existing" for c in chats)


@pytest.mark.asyncio
async def test_digest_delivery_only_control_group_and_idempotent(d9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9b")
    _env_digest(monkeypatch)
    fixed = datetime(2025, 6, 13, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    monkeypatch.setattr("pb_studio.project_digests.service.summaries_clock", lambda: fixed)

    client, session = d9_client
    headers = {"Authorization": "Bearer adm9b"}
    await client.post("/projects", headers=headers, json={"slug": "del", "name": "Del"})
    pid = (await client.get("/projects", headers=headers)).json()[0]["id"]
    await client.post("/events/telegram", json=_msg(882001, -88201))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -88201})
    await client.post("/events/telegram", json=_msg(882002, -88202))
    ch = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -88202))
    p0, _ = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=ch.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=1),
            text="x",
            raw_message={"from": {"id": 1, "is_bot": False}, "text": "x"},
        )
    )
    await session.commit()
    await client.post(
        f"/projects/{pid}/bind-chat",
        headers=headers,
        json={"chat_id": str(ch.id), "role_in_project": "secondary"},
    )
    d = await client.post(f"/projects/{pid}/digests/today", headers=headers)
    did = d.json()["id"]

    mock_send = AsyncMock(return_value=(True, 200, "", 12001))
    settings = get_settings()
    row = await session.get(StudioProjectDigest, UUID(did))
    assert row is not None
    out1 = await try_deliver_project_digest_row(session, row, settings, send_message=mock_send)
    assert out1 == "delivered"
    assert mock_send.await_args.kwargs["chat_id"] == -88201
    out2 = await try_deliver_project_digest_row(session, row, settings, send_message=mock_send)
    assert out2 == "skipped_already_delivered"


@pytest.mark.asyncio
async def test_digest_command_requires_control_group_scan(d9_client, monkeypatch):
    _env_digest(monkeypatch)
    client, session = d9_client
    await client.post("/events/telegram", json=_msg(883001, -88301))
    await client.post("/events/telegram", json=_msg(883002, -88302))
    await client.post(
        "/events/telegram",
        json=_msg(883003, -88302, text="/project_digest_today nope", message_id=3),
    )
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=AsyncMock(return_value=(True, 200, "", 1)))
    await session.commit()
    assert await session.scalar(select(func.count()).select_from(StudioControlCommand)) == 0


@pytest.mark.asyncio
async def test_digest_command_acl_denied(d9_client, monkeypatch):
    _env_digest(monkeypatch)
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9b")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "1")
    get_settings.cache_clear()
    client, session = d9_client
    headers = {"Authorization": "Bearer adm9b"}
    await client.post("/projects", headers=headers, json={"slug": "acl", "name": "Acl"})
    await client.post("/events/telegram", json=_msg(884001, -88401))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -88401})
    await client.post(
        "/events/telegram",
        json=_msg(
            884002,
            -88401,
            text="/project_digest_today acl",
            message_id=2,
            from_user_id=99,
        ),
    )
    await run_control_commands_cycle(
        session,
        get_settings(),
        send_message=AsyncMock(return_value=(True, 200, "", 2)),
    )
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED


@pytest.mark.asyncio
async def test_digest_api_requires_admin_token(d9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "sec")
    get_settings.cache_clear()
    client, _s = d9_client
    r = await client.get("/project-digests/00000000-0000-0000-0000-000000000001")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_summary_help_still_works_with_digest_parser(d9_client, monkeypatch):
    _env_digest(monkeypatch)
    client, session = d9_client
    await client.post("/events/telegram", json=_msg(885001, -88501))
    await client.post("/control-group/set", json={"telegram_chat_id": -88501})
    await client.post("/events/telegram", json=_msg(885002, -88501, text="/summary_help", message_id=2))
    mock_send = AsyncMock(return_value=(True, 200, "", 3))
    await run_control_commands_cycle(session, get_settings(), send_message=mock_send)
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.command_name == ControlCommandName.SUMMARY_HELP


@pytest.mark.asyncio
async def test_no_httpx_on_digest_command_with_mocked_send(d9_client, monkeypatch):
    _env_digest(monkeypatch)
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9b")
    get_settings.cache_clear()
    client, session = d9_client
    headers = {"Authorization": "Bearer adm9b"}
    await client.post("/projects", headers=headers, json={"slug": "htt", "name": "Htt"})
    await client.post("/events/telegram", json=_msg(886001, -88601))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -88601})
    await client.post(
        "/events/telegram",
        json=_msg(886002, -88601, text="/project_digest_today htt", message_id=2),
    )

    async def boom(*_a, **_k):
        raise AssertionError("httpx.AsyncClient must not be used")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    await run_control_commands_cycle(
        session,
        get_settings(),
        send_message=AsyncMock(return_value=(True, 200, "", 9)),
    )
    await session.commit()


def test_celery_project_digest_tasks_registered():
    assert "pb_studio.worker.generate_daily_project_digests" in celery_app.tasks
    assert "pb_studio.worker.deliver_pending_project_digests" in celery_app.tasks
