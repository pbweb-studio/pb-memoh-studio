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
from pb_studio.worker.tasks import process_control_group_commands, process_control_group_summary_commands


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


def test_parser_slash_command_with_bot_suffix():
    p = parse_control_group_command_line("/kb_help@jarvispbweb_bot")
    assert p is not None
    assert p.name == ControlCommandName.KB_HELP
    p2 = parse_control_group_command_line("/summary_help@some_bot")
    assert p2 is not None
    assert p2.name == ControlCommandName.SUMMARY_HELP
    p3 = parse_control_group_command_line("/project_list@b")
    assert p3 is not None
    assert p3.name == ControlCommandName.PROJECT_LIST
    p4 = parse_control_group_command_line("/rule_help@x")
    assert p4 is not None
    assert p4.name == ControlCommandName.RULE_HELP


def test_parser_kb_import_last_with_bot_suffix():
    p = parse_control_group_command_line("/kb_import_last@botname My Document Title")
    assert p is not None
    assert p.name == ControlCommandName.KB_IMPORT_LAST
    assert p.args["title"] == "My Document Title"


def test_period_bounds_rejects_inverted():
    with pytest.raises(ValueError):
        period_bounds_utc("2025-01-10", "2025-01-05")


def test_celery_process_control_task_registered():
    assert "pb_studio.worker.process_control_group_summary_commands" in celery_app.tasks
    assert "pb_studio.worker.process_control_group_commands" in celery_app.tasks


def test_celery_beat_schedule_includes_process_control_group_commands():
    bs = celery_app.conf.beat_schedule or {}
    entry = bs.get("studio-process-control-group-commands")
    assert entry is not None
    assert entry["task"] == "pb_studio.worker.process_control_group_commands"


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


def test_celery_process_control_group_commands_invokes_runner(monkeypatch):
    import inspect

    def fake_run(coro):
        assert inspect.iscoroutine(coro)
        assert coro.__name__ == "run_control_commands_standalone"
        coro.close()
        return {"scan": {}, "process": {}}

    monkeypatch.setattr("pb_studio.worker.tasks.asyncio.run", fake_run)
    out = process_control_group_commands()
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


@pytest.mark.asyncio
async def test_summary_chats_excludes_control_group(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780001, -78001))
    await client.post("/control-group/set", json={"telegram_chat_id": -78001})
    await client.post("/events/telegram", json=_msg(780002, -78002))
    await client.post("/events/telegram", json=_msg(780003, -78003))
    cg = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -78001))
    assert cg is not None
    await client.post("/events/telegram", json=_msg(780004, -78001, text="/summary_chats", message_id=5))
    mock = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=mock)
    await session.commit()
    body = str(mock.await_args)
    assert str(cg.id) not in body
    assert "-78002" in body and "-78003" in body


@pytest.mark.asyncio
async def test_summary_all_today_multiple_chats(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    fixed = datetime(2025, 9, 9, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780101, -78101))
    await client.post("/control-group/set", json={"telegram_chat_id": -78101})
    await client.post("/events/telegram", json=_msg(780102, -78102))
    await client.post("/events/telegram", json=_msg(780103, -78103))
    t2 = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -78102))
    t3 = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -78103))
    p0, _ = utc_day_bounds(fixed.date())
    for ch in (t2, t3):
        assert ch is not None
        session.add(
            StudioMessage(
                chat_id=ch.id,
                telegram_message_id=2,
                date=p0 + timedelta(hours=1),
                text="line",
                raw_message={"from": {"id": 1, "is_bot": False}, "text": "line"},
            )
        )
    await session.commit()
    await client.post("/events/telegram", json=_msg(780104, -78101, text="/summary_all_today", message_id=8))
    mock = AsyncMock(return_value=(True, 200, "", 2))
    await run_control_commands_cycle(session, get_settings(), send_message=mock)
    await session.commit()
    n = await session.scalar(select(func.count()).select_from(StudioChatSummary))
    assert n >= 2
    assert "Сводки" in str(mock.await_args)


@pytest.mark.asyncio
async def test_summary_all_yesterday_idempotent_two_cycles(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    fixed = datetime(2025, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780201, -78201))
    await client.post("/control-group/set", json={"telegram_chat_id": -78201})
    await client.post("/events/telegram", json=_msg(780202, -78202))
    t2 = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -78202))
    assert t2 is not None
    p0, _ = utc_day_bounds((fixed.date() - timedelta(days=1)))
    session.add(
        StudioMessage(
            chat_id=t2.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=2),
            text="y",
            raw_message={"from": {"id": 1, "is_bot": False}, "text": "y"},
        )
    )
    await session.commit()
    await client.post("/events/telegram", json=_msg(780203, -78201, text="/summary_all_yesterday", message_id=3))
    mock = AsyncMock(return_value=(True, 200, "", 1))
    s = get_settings()
    await run_control_commands_cycle(session, s, send_message=mock)
    await session.commit()
    n1 = await session.scalar(select(func.count()).select_from(StudioChatSummary))
    await client.post("/events/telegram", json=_msg(780204, -78201, text="/summary_all_yesterday", message_id=4))
    await run_control_commands_cycle(session, s, send_message=mock)
    await session.commit()
    n2 = await session.scalar(select(func.count()).select_from(StudioChatSummary))
    assert n2 == n1


@pytest.mark.asyncio
async def test_acl_denied_no_summary(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "999")
    get_settings.cache_clear()
    fixed = datetime(2025, 11, 5, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780301, -78301))
    await client.post("/control-group/set", json={"telegram_chat_id": -78301})
    await client.post("/events/telegram", json=_msg(780302, -78302))
    target = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -78302))
    assert target is not None
    p0, _ = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=target.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=1),
            text="acl",
            raw_message={"from": {"id": 1, "is_bot": False}, "text": "acl"},
        )
    )
    await session.commit()
    await client.post(
        "/events/telegram",
        json=_msg(780303, -78301, text=f"/summary_today {target.id}", message_id=5, from_user_id=42),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 9)))
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED
    n = await session.scalar(select(func.count()).select_from(StudioChatSummary))
    assert n == 0


@pytest.mark.asyncio
async def test_acl_allowed_matching_sender(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "42, 100")
    get_settings.cache_clear()
    fixed = datetime(2025, 11, 6, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780401, -78401))
    await client.post("/control-group/set", json={"telegram_chat_id": -78401})
    await client.post("/events/telegram", json=_msg(780402, -78402))
    target = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -78402))
    assert target is not None
    p0, _ = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=target.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=1),
            text="okacl",
            raw_message={"from": {"id": 1, "is_bot": False}, "text": "okacl"},
        )
    )
    await session.commit()
    await client.post(
        "/events/telegram",
        json=_msg(780403, -78401, text=f"/summary_today {target.id}", message_id=5, from_user_id=100),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 9)))
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd.status == ControlCommandStatus.PROCESSED


@pytest.mark.asyncio
async def test_long_all_summary_truncated(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    monkeypatch.setattr("pb_studio.control_commands.service.TELEGRAM_TEXT_SAFE_MAX", 250)
    fixed = datetime(2025, 12, 2, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780501, -78501))
    await client.post("/control-group/set", json={"telegram_chat_id": -78501})
    for i in range(6):
        tid = -78510 - i
        await client.post("/events/telegram", json=_msg(780510 + i, tid))
        ch = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == tid))
        assert ch is not None
        p0, _ = utc_day_bounds(fixed.date())
        session.add(
            StudioMessage(
                chat_id=ch.id,
                telegram_message_id=2,
                date=p0 + timedelta(hours=1),
                text="x" * 400,
                raw_message={"from": {"id": 1, "is_bot": False}, "text": "x" * 400},
            )
        )
    await session.commit()
    await client.post("/events/telegram", json=_msg(780599, -78501, text="/summary_all_today", message_id=50))
    mock = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=mock)
    await session.commit()
    txt = str(mock.await_args)
    assert "обрезан" in txt


@pytest.mark.asyncio
async def test_long_chats_list_truncated(cc_client, monkeypatch):
    _env_7a(monkeypatch)
    monkeypatch.setattr("pb_studio.control_commands.service.SUMMARY_CHATS_MAX_LINES", 4)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780601, -78601))
    await client.post("/control-group/set", json={"telegram_chat_id": -78601})
    for i in range(8):
        await client.post("/events/telegram", json=_msg(780610 + i, -78620 - i))
    await client.post("/events/telegram", json=_msg(780699, -78601, text="/summary_chats", message_id=9))
    mock = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=mock)
    await session.commit()
    txt = str(mock.await_args)
    assert "обрезан" in txt


@pytest.mark.asyncio
async def test_access_denied_audit_and_no_token_in_last_error(cc_client, monkeypatch):
    from pb_studio.event_mirror.models import AuditLog

    _env_7a(monkeypatch)
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "MYSECRETBOTTOKENZZ")
    get_settings.cache_clear()
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780701, -78701))
    await client.post("/control-group/set", json={"telegram_chat_id": -78701})
    await client.post("/events/telegram", json=_msg(780702, -78701, text="/summary_help", message_id=3, from_user_id=2))
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED
    assert "MYSECRET" not in (cmd.last_error or "")
    assert "ZZ" not in (cmd.last_error or "")
    aud = await session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "control_commands.access_denied")
    )
    assert aud >= 1


@pytest.mark.asyncio
async def test_get_control_commands_filter_command_name(cc_client, monkeypatch):
    from pb_studio.control_group.service import get_control_group_chat

    _env_7a(monkeypatch)
    client, session = cc_client
    await client.post("/events/telegram", json=_msg(780801, -78801))
    await client.post("/control-group/set", json={"telegram_chat_id": -78801})
    await client.post("/events/telegram", json=_msg(780802, -78801, text="/summary_chats", message_id=2))
    session.expire_all()
    assert await get_control_group_chat(session) is not None
    out = await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    assert out["scan"]["inserted"] >= 1, out
    await session.commit()
    session.expire_all()
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm7b")
    get_settings.cache_clear()
    r = await client.get(
        "/control-commands",
        params={"command_name": "summary_chats"},
        headers={"Authorization": "Bearer adm7b"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert all(row["command_name"] == "summary_chats" for row in data)


def test_parser_summary_chats_no_args():
    p = parse_control_group_command_line("/summary_chats")
    assert p is not None and p.name == ControlCommandName.SUMMARY_CHATS


def test_parser_summary_all_today():
    p = parse_control_group_command_line("/summary_all_today")
    assert p is not None and p.name == ControlCommandName.SUMMARY_ALL_TODAY


def test_redact_secrets_strips_bot_token():
    from pb_studio.control_group.telegram_outbound import redact_secrets

    tok = "bot-secret-99"
    assert tok not in redact_secrets(f"failed {tok} err", tok)
