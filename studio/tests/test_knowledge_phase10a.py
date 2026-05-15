from __future__ import annotations

from unittest.mock import AsyncMock
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pb_studio.control_commands.models  # noqa: F401
import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.knowledge.models  # noqa: F401
import pb_studio.project_digests.models  # noqa: F401
import pb_studio.projects.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_commands.constants import ControlCommandName, ControlCommandStatus
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.control_commands.service import run_control_commands_cycle
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.knowledge import service as kb_service
from pb_studio.knowledge.constants import KnowledgeDocumentStatus, KnowledgeVersionStatus
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def kb_engine():
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
async def kb_client(kb_engine):
    factory = async_sessionmaker(kb_engine, class_=AsyncSession, expire_on_commit=False)
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


def _kb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "80")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "15")
    get_settings.cache_clear()


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


def test_split_text_overlap():
    body = "x" * 250
    parts = kb_service.split_text_into_chunks(body, max_chars=100, overlap_chars=20)
    assert len(parts) >= 3
    assert all(len(p) <= 100 for p in parts)
    if len(parts) >= 2:
        tail = parts[0][-20:]
        head = parts[1][:20]
        assert tail == head


@pytest.mark.asyncio
async def test_kb_document_create_and_version_chunks(kb_client, monkeypatch):
    _kb_env(monkeypatch)
    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}

    r = await client.post(
        "/knowledge/documents",
        headers=headers,
        json={"title": "Doc A", "source_type": "manual", "status": "draft"},
    )
    assert r.status_code == 201
    doc_id = r.json()["id"]

    r2 = await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=headers,
        json={"text": "y" * 200},
    )
    assert r2.status_code == 200
    ver_id = r2.json()["id"]
    assert r2.json()["status"] == KnowledgeVersionStatus.PARSED

    ch = await client.get(f"/knowledge/versions/{ver_id}/chunks", headers=headers)
    assert ch.status_code == 200
    chunks = ch.json()
    assert len(chunks) >= 2
    assert chunks[0]["chunk_index"] == 0
    assert chunks[1]["chunk_index"] == 1
    if len(chunks) >= 2:
        assert chunks[0]["content_text"][-15:] == chunks[1]["content_text"][:15]


@pytest.mark.asyncio
async def test_kb_same_content_hash_no_duplicate_version(kb_client, monkeypatch):
    _kb_env(monkeypatch)
    client, _session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    r = await client.post("/knowledge/documents", headers=headers, json={"title": "H", "status": "draft"})
    doc_id = r.json()["id"]
    text = "identical-body"
    v1 = await client.post(
        f"/knowledge/documents/{doc_id}/versions/text", headers=headers, json={"text": text}
    )
    v2 = await client.post(
        f"/knowledge/documents/{doc_id}/versions/text", headers=headers, json={"text": text}
    )
    assert v1.status_code == 200 and v2.status_code == 200
    assert v1.json()["id"] == v2.json()["id"]
    versions = await client.get(f"/knowledge/documents/{doc_id}/versions", headers=headers)
    assert len(versions.json()) == 1


@pytest.mark.asyncio
async def test_kb_project_link_and_archive(kb_client, monkeypatch):
    _kb_env(monkeypatch)
    client, _session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    pr = await client.post("/projects", headers=headers, json={"slug": "kbp", "name": "KB Proj"})
    pid = pr.json()["id"]

    r = await client.post(
        "/knowledge/documents",
        headers=headers,
        json={"title": "Linked", "project_id": pid},
    )
    assert r.status_code == 201
    assert r.json()["project_id"] == pid

    doc_id = r.json()["id"]
    ar = await client.post(f"/knowledge/documents/{doc_id}/archive", headers=headers)
    assert ar.status_code == 200
    assert ar.json()["status"] == KnowledgeDocumentStatus.ARCHIVED


@pytest.mark.asyncio
async def test_kb_api_requires_admin_token(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "secretkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    get_settings.cache_clear()
    client, _session = kb_client
    r = await client.get("/knowledge/documents")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_kb_api_503_when_disabled(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "false")
    get_settings.cache_clear()
    client, _session = kb_client
    r = await client.get("/knowledge/documents", headers={"Authorization": "Bearer admkb"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_kb_add_from_control_group(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    get_settings.cache_clear()

    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    await client.post("/events/telegram", json=_msg(990001, -99001))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -99001})

    await client.post(
        "/events/telegram",
        json=_msg(
            990002,
            -99001,
            text="/kb_add My title | body text here",
            message_id=2,
        ),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd is not None
    assert cmd.command_name == ControlCommandName.KB_ADD
    assert cmd.status == ControlCommandStatus.PROCESSED


@pytest.mark.asyncio
async def test_kb_list_not_scanned_outside_control_group(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    get_settings.cache_clear()
    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    await client.post("/events/telegram", json=_msg(991001, -99101))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -99101})
    await client.post("/events/telegram", json=_msg(991002, -99102, text="/kb_list", message_id=2))
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    q = await session.scalars(select(StudioControlCommand))
    assert list(q.all()) == []


@pytest.mark.asyncio
async def test_kb_help_works_when_kb_disabled(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "false")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    get_settings.cache_clear()

    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    await client.post("/events/telegram", json=_msg(997001, -99701))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -99701})
    mock_send = AsyncMock(return_value=(True, 200, "", 42))
    await client.post(
        "/events/telegram",
        json=_msg(997002, -99701, text="/kb_help@jarvispbweb_bot", message_id=2),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=mock_send)
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd is not None
    assert cmd.command_name == ControlCommandName.KB_HELP
    assert cmd.status == ControlCommandStatus.PROCESSED
    mock_send.assert_awaited()
    sent = mock_send.await_args.kwargs.get("text", "")
    assert "STUDIO_KB_ENABLED: off" in sent


@pytest.mark.asyncio
async def test_kb_acl_denied(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "7")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    get_settings.cache_clear()

    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    await client.post("/events/telegram", json=_msg(992001, -99201))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -99201})
    await client.post(
        "/events/telegram",
        json=_msg(992002, -99201, text="/kb_add T | x", message_id=2, from_user_id=99),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED


@pytest.mark.asyncio
async def test_summary_help_unchanged_for_summary_prefix(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    get_settings.cache_clear()

    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    await client.post("/events/telegram", json=_msg(993001, -99301))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -99301})
    await client.post(
        "/events/telegram",
        json=_msg(993002, -99301, text="/summary_help", message_id=2),
    )
    send = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=send)
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.command_name == ControlCommandName.SUMMARY_HELP
    assert send.await_count >= 1
    call_text = send.call_args.kwargs["text"]
    assert "/summary_today" in call_text


@pytest.mark.asyncio
async def test_project_list_still_works(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    get_settings.cache_clear()

    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    await client.post("/projects", headers=headers, json={"slug": "plx", "name": "PLX"})
    await client.post("/events/telegram", json=_msg(994001, -99401))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -99401})
    await client.post("/events/telegram", json=_msg(994002, -99401, text="/project_list", message_id=2))
    send = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=send)
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.command_name == ControlCommandName.PROJECT_LIST
    assert "plx" in (send.call_args.kwargs.get("text") or "")


@pytest.mark.asyncio
async def test_kb_no_httpx_when_send_mocked(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_BOT_TOKEN_X")
    get_settings.cache_clear()

    def boom(*_a, **_k):
        raise AssertionError("httpx.AsyncClient must not be used")

    monkeypatch.setattr(httpx, "AsyncClient", boom)

    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    await client.post("/events/telegram", json=_msg(995001, -99501))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -99501})
    await client.post("/events/telegram", json=_msg(995002, -99501, text="/kb_list", message_id=2))
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))


@pytest.mark.asyncio
async def test_kb_last_error_redacts_token(kb_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "admkb")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRETBOTTOK")
    get_settings.cache_clear()

    async def boom_send(*_a, **_k):
        raise RuntimeError("fail SECRETBOTTOK")

    client, session = kb_client
    headers = {"Authorization": "Bearer admkb"}
    await client.post("/events/telegram", json=_msg(996001, -99601))
    await client.post("/control-group/set", headers=headers, json={"telegram_chat_id": -99601})
    await client.post(
        "/events/telegram",
        json=_msg(996002, -99601, text="/kb_list", message_id=2),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=boom_send)
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED
    assert cmd.last_error is not None
    assert "SECRETBOTTOK" not in cmd.last_error
