from __future__ import annotations

from unittest.mock import AsyncMock

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
import pb_studio.projects.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_commands.constants import ControlCommandName, ControlCommandStatus
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.control_commands.service import run_control_commands_cycle
from pb_studio.control_group.constants import ChatRole
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import StudioChat
from pb_studio.projects.models import StudioProjectChat
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def p9_engine():
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
async def p9_client(p9_engine):
    factory = async_sessionmaker(p9_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env_control(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_MAX_BATCH", "50")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    monkeypatch.setenv("STUDIO_SUMMARY_DELIVERY_ENABLED", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_projects_api_401_without_bearer_when_admin_token_set(p9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "secret-admin-9a")
    get_settings.cache_clear()
    client, _session = p9_client
    r = await client.get("/projects")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_projects_api_crud_bind_duplicate_unbind_archive(p9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9a")
    get_settings.cache_clear()
    client, session = p9_client
    headers = {"Authorization": "Bearer adm9a"}
    r1 = await client.post("/projects", headers=headers, json={"slug": "alpha", "name": "Alpha"})
    assert r1.status_code == 200
    pid = r1.json()["id"]
    r_dup = await client.post("/projects", headers=headers, json={"slug": "alpha", "name": "Dup"})
    assert r_dup.status_code == 409

    await client.post("/events/telegram", json=_msg(990001, -99001))
    await client.post("/events/telegram", json=_msg(990002, -99002))
    chat_row = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -99002))
    assert chat_row is not None

    b1 = await client.post(
        f"/projects/{pid}/bind-chat",
        headers=headers,
        json={"chat_id": str(chat_row.id), "role_in_project": "secondary"},
    )
    assert b1.status_code == 200
    link_id = b1.json()["id"]
    b2 = await client.post(
        f"/projects/{pid}/bind-chat",
        headers=headers,
        json={"chat_id": str(chat_row.id), "role_in_project": "secondary"},
    )
    assert b2.status_code == 200
    assert b2.json()["id"] == link_id
    n_links = await session.scalar(select(func.count()).select_from(StudioProjectChat))
    assert n_links == 1

    u = await client.post(
        f"/projects/{pid}/unbind-chat",
        headers=headers,
        json={"chat_id": str(chat_row.id)},
    )
    assert u.status_code == 200
    assert u.json()["is_active"] is False
    active = await client.get(f"/projects/{pid}/chats", headers=headers)
    assert active.json() == []
    all_rows = await client.get(f"/projects/{pid}/chats", headers=headers, params={"include_inactive": True})
    assert len(all_rows.json()) == 1

    arch = await client.post(f"/projects/{pid}/archive", headers=headers)
    assert arch.status_code == 200
    assert arch.json()["status"] == "archived"
    r_active = await client.get("/projects", headers=headers, params={"status": "active"})
    assert r_active.status_code == 200
    assert all(row["slug"] != "alpha" for row in r_active.json())

    await client.post("/projects", headers=headers, json={"slug": "beta", "name": "Beta"})
    r2 = await client.get("/projects", headers=headers, params={"status": "active"})
    slugs = {row["slug"] for row in r2.json()}
    assert "beta" in slugs


@pytest.mark.asyncio
async def test_projects_api_bind_rejects_control_group_chat(p9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9a")
    get_settings.cache_clear()
    client, session = p9_client
    headers = {"Authorization": "Bearer adm9a"}
    await client.post("/projects", headers=headers, json={"slug": "g1", "name": "G1"})
    lst = await client.get("/projects", headers=headers)
    pid = lst.json()[0]["id"]

    await client.post("/events/telegram", json=_msg(991001, -99101))
    await client.post(
        "/control-group/set",
        headers=headers,
        json={"telegram_chat_id": -99101},
    )
    cg = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -99101))
    assert cg is not None

    bad = await client.post(
        f"/projects/{pid}/bind-chat",
        headers=headers,
        json={"chat_id": str(cg.id), "role_in_project": "secondary"},
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_projects_api_bind_sets_unknown_to_project_chat(p9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9a")
    get_settings.cache_clear()
    client, session = p9_client
    headers = {"Authorization": "Bearer adm9a"}
    await client.post("/projects", headers=headers, json={"slug": "p2", "name": "P2"})
    pid = (await client.get("/projects", headers=headers)).json()[0]["id"]

    await client.post("/events/telegram", json=_msg(992001, -99201))
    ch = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -99201))
    assert ch is not None
    assert ch.chat_role == ChatRole.UNKNOWN.value

    r_bind = await client.post(
        f"/projects/{pid}/bind-chat",
        headers=headers,
        json={"chat_id": str(ch.id), "role_in_project": "client"},
    )
    assert r_bind.status_code == 200
    await session.refresh(ch)
    assert ch.chat_role == ChatRole.PROJECT_CHAT.value


@pytest.mark.asyncio
async def test_projects_api_unbind_deactivates_only(p9_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9a")
    get_settings.cache_clear()
    client, session = p9_client
    headers = {"Authorization": "Bearer adm9a"}
    await client.post("/projects", headers=headers, json={"slug": "u1", "name": "U1"})
    pid = (await client.get("/projects", headers=headers)).json()[0]["id"]
    await client.post("/events/telegram", json=_msg(993001, -99301))
    ch = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -99301))
    await client.post(
        f"/projects/{pid}/bind-chat",
        headers=headers,
        json={"chat_id": str(ch.id), "role_in_project": "secondary"},
    )
    u = await client.post(
        f"/projects/{pid}/unbind-chat",
        headers=headers,
        json={"chat_id": str(ch.id)},
    )
    assert u.status_code == 200
    assert u.json()["is_active"] is False
    active = await client.get(f"/projects/{pid}/chats", headers=headers)
    assert active.json() == []
    all_rows = await client.get(f"/projects/{pid}/chats", headers=headers, params={"include_inactive": True})
    assert len(all_rows.json()) == 1
    ghost = await session.get(StudioChat, ch.id)
    assert ghost is not None


@pytest.mark.asyncio
async def test_project_command_not_scanned_outside_control_group(p9_client, monkeypatch):
    _env_control(monkeypatch)
    client, session = p9_client
    await client.post("/events/telegram", json=_msg(994001, -99401))
    await client.post("/control-group/set", json={"telegram_chat_id": -99401})
    await client.post("/events/telegram", json=_msg(994002, -99402))
    await client.post(
        "/events/telegram",
        json=_msg(994003, -99402, text="/project_list", message_id=5),
    )
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=AsyncMock(return_value=(True, 200, "", 1)))
    await session.commit()
    n = await session.scalar(select(func.count()).select_from(StudioControlCommand))
    assert n == 0


@pytest.mark.asyncio
async def test_project_commands_acl_denied(p9_client, monkeypatch):
    _env_control(monkeypatch)
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "111")
    get_settings.cache_clear()
    client, session = p9_client
    await client.post("/events/telegram", json=_msg(995001, -99501))
    await client.post("/control-group/set", json={"telegram_chat_id": -99501})
    await client.post(
        "/events/telegram",
        json=_msg(995002, -99501, text="/project_list", message_id=3, from_user_id=222),
    )
    mock_send = AsyncMock(return_value=(True, 200, "", 9001))
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED
    mock_send.assert_awaited()


@pytest.mark.asyncio
async def test_project_bind_rejects_active_control_group_chat(p9_client, monkeypatch):
    _env_control(monkeypatch)
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm9a")
    get_settings.cache_clear()
    client, session = p9_client
    headers = {"Authorization": "Bearer adm9a"}
    await client.post("/projects", headers=headers, json={"slug": "cg", "name": "CG"})
    slug = "cg"

    await client.post("/events/telegram", json=_msg(996001, -99601))
    await client.post(
        "/control-group/set",
        headers=headers,
        json={"telegram_chat_id": -99601},
    )
    cg_chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -99601))
    assert cg_chat is not None

    await client.post(
        "/events/telegram",
        json=_msg(
            996002,
            -99601,
            text=f"/project_bind {slug} {cg_chat.id}",
            message_id=4,
        ),
    )
    mock_send = AsyncMock(return_value=(True, 200, "", 9002))
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.command_name == ControlCommandName.PROJECT_BIND
    assert cmd.status == ControlCommandStatus.PROCESSED
    assert mock_send.await_count >= 1
    reply_text = mock_send.await_args.kwargs["text"]
    assert "control group" in reply_text.lower() or "cannot bind" in reply_text.lower()


@pytest.mark.asyncio
async def test_project_reply_sendmessage_only_to_control_group(p9_client, monkeypatch):
    _env_control(monkeypatch)
    client, session = p9_client
    await client.post("/events/telegram", json=_msg(997001, -99701))
    await client.post("/control-group/set", json={"telegram_chat_id": -99701})
    await client.post(
        "/events/telegram",
        json=_msg(997002, -99701, text="/project_help", message_id=2),
    )
    mock_send = AsyncMock(return_value=(True, 200, "", 8001))
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    mock_send.assert_awaited()
    assert mock_send.await_args.kwargs["chat_id"] == -99701


@pytest.mark.asyncio
async def test_summary_help_untouched_by_project_dispatch(p9_client, monkeypatch):
    _env_control(monkeypatch)
    client, session = p9_client
    await client.post("/events/telegram", json=_msg(998001, -99801))
    await client.post("/control-group/set", json={"telegram_chat_id": -99801})
    await client.post(
        "/events/telegram",
        json=_msg(998002, -99801, text="/summary_help", message_id=2),
    )
    mock_send = AsyncMock(return_value=(True, 200, "", 8002))
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.command_name == ControlCommandName.SUMMARY_HELP
    assert cmd.status == ControlCommandStatus.PROCESSED


@pytest.mark.asyncio
async def test_project_list_failure_redacts_bot_token_in_last_error(p9_client, monkeypatch):
    _env_control(monkeypatch)
    client, session = p9_client
    await client.post("/events/telegram", json=_msg(999001, -99901))
    await client.post("/control-group/set", json={"telegram_chat_id": -99901})
    await client.post(
        "/events/telegram",
        json=_msg(999002, -99901, text="/project_list", message_id=2),
    )

    async def boom(*_a, **_k):
        raise RuntimeError("boom TEST_BOT_TOKEN_X end")

    monkeypatch.setattr(
        "pb_studio.control_commands.service.studio_projects_service.list_projects",
        boom,
    )
    mock_send = AsyncMock(return_value=(True, 200, "", 1))
    settings = get_settings()
    await run_control_commands_cycle(session, settings, send_message=mock_send)
    await session.commit()
    cmd = await session.scalar(select(StudioControlCommand))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED
    assert cmd.last_error
    assert "TEST_BOT_TOKEN_X" not in (cmd.last_error or "")


@pytest.mark.asyncio
async def test_no_httpx_when_send_mocked_project_list(p9_client, monkeypatch):
    _env_control(monkeypatch)
    client, session = p9_client
    await client.post("/events/telegram", json=_msg(1000001, -100001))
    await client.post("/control-group/set", json={"telegram_chat_id": -100001})
    await client.post(
        "/events/telegram",
        json=_msg(1000002, -100001, text="/project_list", message_id=2),
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
