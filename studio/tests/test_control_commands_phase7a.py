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

import pb_studio.control_commands.models  # noqa: F401
import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.celery_app import celery_app
from pb_studio.control_commands.constants import ControlCommandName, ControlCommandStatus
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.control_commands.parser import parse_control_group_command_line, period_bounds_utc
from pb_studio.control_commands.service import run_control_commands_cycle
from pb_studio.control_group.constants import ChatRole
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.response_queue.models import Base
from pb_studio.summaries.constants import SummaryStatus, SummaryType
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.planner import utc_day_bounds
from pb_studio.worker.tasks import process_control_group_summary_commands


@pytest_asyncio.fixture
async def cc_engine():
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
async def cc_client(cc_engine):
    factory = async_sessionmaker(cc_engine, class_=AsyncSession, expire_on_commit=False)
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


def _msg(update_id: int, chat_id: int, *, text: str = "hello", message_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "T"},
            "from": {"id": 42, "is_bot": False, "first_name": "U"},
            "text": text,
        },
    }


def _env_7a(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_MAX_BATCH", "50")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    monkeypatch.setenv("STUDIO_SUMMARY_DELIVERY_ENABLED", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_summary_today_scans_processes_delivers_text(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    fixed = datetime(2025, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)

    mock_send = AsyncMock(return_value=(True, 200, "", 777001))

    client, session = cc_client
    await client.post("/events/telegram", json=_msg(770001, -77001))
    await client.post("/control-group/set", json={"telegram_chat_id": -77001})
    await client.post("/events/telegram", json=_msg(770002, -77002))
    target = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -77002))
    assert target is not None
    p0, _p1 = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=target.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=2),
            text="visible for today",
            raw_message={"from": {"id": 9, "is_bot": False}, "text": "visible for today"},
        )
    )
    await session.commit()

    cmd_text = f"/summary_today {target.id}"
    await client.post("/events/telegram", json=_msg(770003, -77001, text=cmd_text, message_id=10))

    settings = get_settings()
    out1 = await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    assert out1["scan"]["inserted"] >= 1
    assert out1["process"]["processed"] >= 1
    assert mock_send.await_count >= 1

    mock_send.reset_mock()
    out2 = await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    assert out2["scan"]["inserted"] == 0
    assert out2["process"]["processed"] == 0

    n_cmd = await session.scalar(select(func.count()).select_from(StudioControlCommand))
    assert n_cmd == 1
    row = await session.scalar(select(StudioControlCommand))
    assert row is not None
    assert row.status == ControlCommandStatus.PROCESSED
    assert row.result_summary_id is not None


@pytest.mark.asyncio
async def test_client_chat_command_not_scanned(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(770101, -77101))
    await client.post("/control-group/set", json={"telegram_chat_id": -77101})
    await client.post("/events/telegram", json=_msg(770102, -77102))
    target = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -77102))
    assert target is not None
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm771")
    get_settings.cache_clear()
    client_chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -77102))
    assert client_chat is not None
    r = await client.post(
        f"/chats/{client_chat.id}/role",
        json={"role": ChatRole.CLIENT_CHAT.value},
        headers={"Authorization": "Bearer adm771"},
    )
    assert r.status_code == 200
    await client.post(
        "/events/telegram",
        json=_msg(770103, -77102, text=f"/summary_today {target.id}", message_id=5),
    )
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=AsyncMock(return_value=(True, 200, "", 1)))
    await session.commit()
    n = await session.scalar(select(func.count()).select_from(StudioControlCommand))
    assert n == 0


@pytest.mark.asyncio
async def test_unknown_chat_uuid_fails_without_batch_abort(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(770201, -77201))
    await client.post("/control-group/set", json={"telegram_chat_id": -77201})
    ghost = uuid4()
    await client.post(
        "/events/telegram",
        json=_msg(770202, -77201, text=f"/summary_today {ghost}", message_id=3),
    )
    settings = get_settings()
    mock_send = AsyncMock(return_value=(True, 200, "", 888))
    await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED
    assert cmd.last_error


@pytest.mark.asyncio
async def test_summary_period_invalid_order_fails(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    fixed = datetime(2025, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(770301, -77301))
    await client.post("/control-group/set", json={"telegram_chat_id": -77301})
    await client.post("/events/telegram", json=_msg(770302, -77302))
    target = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -77302))
    assert target is not None
    await client.post(
        "/events/telegram",
        json=_msg(
            770303,
            -77301,
            text=f"/summary_period {target.id} 2025-10-20 2025-10-01",
            message_id=4,
        ),
    )
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=AsyncMock(return_value=(True, 200, "", 1)))
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED


@pytest.mark.asyncio
async def test_summary_latest_picks_newest_generated(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(770401, -77401))
    await client.post("/control-group/set", json={"telegram_chat_id": -77401})
    await client.post("/events/telegram", json=_msg(770402, -77402))
    target = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -77402))
    assert target is not None
    p0 = datetime(2025, 4, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    older = StudioChatSummary(
        chat_id=target.id,
        chat_role=ChatRole.CLIENT_CHAT.value,
        summary_type=SummaryType.MANUAL,
        period_start=p0,
        period_end=p1,
        status=SummaryStatus.GENERATED,
        source_event_count=0,
        summary_text="older line",
        generated_at=p0,
    )
    session.add(older)
    newer = StudioChatSummary(
        chat_id=target.id,
        chat_role=ChatRole.CLIENT_CHAT.value,
        summary_type=SummaryType.MANUAL,
        period_start=p1,
        period_end=p1 + timedelta(days=1),
        status=SummaryStatus.GENERATED,
        source_event_count=0,
        summary_text="newer line",
        generated_at=p1 + timedelta(hours=5),
    )
    session.add(newer)
    await session.commit()

    await client.post(
        "/events/telegram",
        json=_msg(770403, -77401, text=f"/summary_latest {target.id}", message_id=7),
    )
    settings = get_settings()
    mock_send = AsyncMock(return_value=(True, 200, "", 999))
    await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.PROCESSED
    assert cmd.result_summary_id == newer.id
    mock_send.assert_awaited()
    body = str(mock_send.await_args)
    assert "newer line" in body


@pytest.mark.asyncio
async def test_summary_help_processed(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(770501, -77501))
    await client.post("/control-group/set", json={"telegram_chat_id": -77501})
    await client.post("/events/telegram", json=_msg(770502, -77501, text="/summary_help", message_id=2))
    settings = get_settings()
    mock_send = AsyncMock(return_value=(True, 200, "", 1001))
    await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.command_name == ControlCommandName.SUMMARY_HELP
    assert cmd.status == ControlCommandStatus.PROCESSED


@pytest.mark.asyncio
async def test_get_control_commands_requires_admin(cc_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "only7a")
    get_settings.cache_clear()
    client, _ = cc_client
    r = await client.get("/control-commands")
    assert r.status_code == 401
    r2 = await client.get("/control-commands", headers={"Authorization": "Bearer only7a"})
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_post_process_pending_api(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(770601, -77601))
    r_set = await client.post("/control-group/set", json={"telegram_chat_id": -77601})
    assert r_set.status_code == 200, r_set.text
    await client.post("/events/telegram", json=_msg(770602, -77602))
    await client.post("/events/telegram", json=_msg(770602, -77602))
    target = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -77602))
    assert target is not None
    fixed = datetime(2025, 11, 11, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    p0, _ = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=target.id,
            telegram_message_id=3,
            date=p0 + timedelta(hours=1),
            text="api day",
            raw_message={"from": {"id": 1, "is_bot": False}, "text": "api day"},
        )
    )
    await session.commit()
    await client.post(
        "/events/telegram",
        json=_msg(770603, -77601, text=f"/summary_today {target.id}", message_id=9),
    )
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "proc7a")
    get_settings.cache_clear()
    s = get_settings()
    assert s.studio_control_commands_enabled
    r = await client.post(
        "/control-commands/process-pending",
        headers={"Authorization": "Bearer proc7a"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "scan" in body and "process" in body
    assert body["scan"]["inserted"] >= 1, body
    assert body["process"]["processed"] >= 1, body
    session.expire_all()
    n = await session.scalar(select(func.count()).select_from(StudioControlCommand))
    assert n == 1


def test_parser_summary_help():
    p = parse_control_group_command_line("/summary_help")
    assert p is not None
    assert p.name == ControlCommandName.SUMMARY_HELP


def test_parser_invalid_uuid_unknown():
    p = parse_control_group_command_line("/summary_today not-a-uuid")
    assert p is not None
    assert p.name == ControlCommandName.UNKNOWN


def test_period_bounds_rejects_inverted():
    with pytest.raises(ValueError):
        period_bounds_utc("2025-01-10", "2025-01-05")


def test_celery_process_control_task_registered():
    assert "pb_studio.worker.process_control_group_summary_commands" in celery_app.tasks


def test_celery_process_control_invokes_runner(monkeypatch):
    import inspect

    def fake_run(coro):
        assert inspect.iscoroutine(coro)
        assert coro.__name__ == "run_control_commands_standalone"
        coro.close()
        return {"scan": {}, "process": {}}

    monkeypatch.setattr("pb_studio.worker.tasks.asyncio.run", fake_run)
    out = process_control_group_summary_commands()
    assert "process" in out


@pytest.mark.asyncio
async def test_no_httpx_when_send_mocked(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(770701, -77701))
    await client.post("/control-group/set", json={"telegram_chat_id": -77701})
    await client.post("/events/telegram", json=_msg(770702, -77702))
    target = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -77702))
    assert target is not None
    fixed = datetime(2025, 12, 1, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    p0, _ = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=target.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=1),
            text="httpx guard",
            raw_message={"from": {"id": 2, "is_bot": False}, "text": "httpx guard"},
        )
    )
    await session.commit()
    await client.post(
        "/events/telegram",
        json=_msg(770703, -77701, text=f"/summary_today {target.id}", message_id=8),
    )

    async def boom(*_a, **_k):
        raise AssertionError("httpx.AsyncClient must not be used when send_message is injected")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    settings = get_settings()
    await run_control_commands_cycle(
        session,
        settings,
        send_message=AsyncMock(return_value=(True, 200, "", 500)),
    )
    await session.commit()


def test_redact_secrets_strips_bot_token():
    from pb_studio.control_group.telegram_outbound import redact_secrets

    tok = "bot-secret-99"
    assert tok not in redact_secrets(f"failed {tok} err", tok)
