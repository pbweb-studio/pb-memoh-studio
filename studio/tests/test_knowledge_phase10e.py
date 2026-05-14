"""Фаза 10e: RAG-ответы по KB (retrieval + OpenAI-compatible chat completion)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

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
from pb_studio.knowledge.constants import KNOWLEDGE_RAG_NOT_FOUND_ANSWER
from pb_studio.response_queue.models import Base
from pb_studio.response_queue.service import QueueService


@pytest_asyncio.fixture
async def k10e_engine():
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
async def k10e_client(k10e_engine):
    factory = async_sessionmaker(k10e_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env10e(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10e")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_RAG_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "500")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "10")
    monkeypatch.setenv("STUDIO_KB_SEARCH_TOP_K", "5")
    monkeypatch.setenv("STUDIO_KB_CHAT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("STUDIO_KB_CHAT_API_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("STUDIO_KB_CHAT_API_KEY", "sk-dummy-chat")
    monkeypatch.setenv("STUDIO_KB_CHAT_MODEL", "test-chat-model")
    get_settings.cache_clear()


def _msg(update_id: int, chat_id: int, *, text: str, message_id: int = 1, from_user_id: int = 42) -> dict:
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


@pytest.mark.asyncio
async def test_knowledge_ask_returns_answer_and_sources(k10e_client, monkeypatch):
    _env10e(monkeypatch)

    async def fake_chat(settings, *, system_prompt: str, user_prompt: str) -> str:
        assert "phase10e_unique_snippet" in user_prompt
        assert len(system_prompt) > 20
        return "Ответ из тестового chat completion."

    monkeypatch.setattr("pb_studio.knowledge.rag._openai_compatible_chat", fake_chat)

    client, _session = k10e_client
    h = {"Authorization": "Bearer adm10e"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "RAG", "status": "draft"})
    doc_id = d.json()["id"]
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "phase10e_unique_snippet для RAG теста", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    r = await client.post("/knowledge/ask", headers=h, json={"question": "что такое phase10e_unique_snippet?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Ответ из тестового chat completion."
    assert len(body["sources"]) >= 1


@pytest.mark.asyncio
async def test_knowledge_ask_filters_by_empty_project(k10e_client, monkeypatch):
    _env10e(monkeypatch)

    async def no_chat(*_a, **_k):
        raise AssertionError("chat must not be called when retrieval is empty")

    monkeypatch.setattr("pb_studio.knowledge.rag._openai_compatible_chat", no_chat)

    client, _session = k10e_client
    h = {"Authorization": "Bearer adm10e"}
    p = await client.post("/projects", headers=h, json={"slug": "emptyproj10e", "name": "Empty"})
    empty_pid = UUID(p.json()["id"])
    d = await client.post("/knowledge/documents", headers=h, json={"title": "Global", "project_id": None})
    await client.post(
        f"/knowledge/documents/{d.json()['id']}/versions/text",
        headers=h,
        json={"text": "only_in_global_doc_token_10e_xyz", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    r = await client.post(
        "/knowledge/ask",
        headers=h,
        json={"question": "only_in_global_doc_token_10e_xyz", "project_id": str(empty_pid)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sources"] == []
    assert body["answer"] == KNOWLEDGE_RAG_NOT_FOUND_ANSWER


@pytest.mark.asyncio
async def test_knowledge_ask_requires_admin_token(k10e_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "secret-admin")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_RAG_ENABLED", "true")
    get_settings.cache_clear()
    client, _session = k10e_client
    r = await client.post("/knowledge/ask", json={"question": "hi"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_knowledge_ask_requires_rag_flag(k10e_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10e")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_RAG_ENABLED", "false")
    get_settings.cache_clear()
    client, _session = k10e_client
    r = await client.post("/knowledge/ask", headers={"Authorization": "Bearer adm10e"}, json={"question": "hi"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_knowledge_ask_chat_error_redacts_api_key(k10e_client, monkeypatch):
    _env10e(monkeypatch)
    leak = "sk-dummy-chat-UNIQUE-LEAK-10e"

    async def boom(settings, *, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError(f"upstream failed: {leak}")

    monkeypatch.setattr("pb_studio.knowledge.rag._openai_compatible_chat", boom)
    client, _session = k10e_client
    h = {"Authorization": "Bearer adm10e"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "E", "status": "draft"})
    await client.post(
        f"/knowledge/documents/{d.json()['id']}/versions/text",
        headers=h,
        json={"text": "body for ask error path 10e", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    r = await client.post("/knowledge/ask", headers=h, json={"question": "body for ask error"})
    assert r.status_code == 400
    assert leak not in r.text


@pytest.mark.asyncio
async def test_kb_ask_acl_denied(k10e_client, monkeypatch):
    _env10e(monkeypatch)
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK10e")
    get_settings.cache_clear()

    client, session = k10e_client
    h = {"Authorization": "Bearer adm10e"}
    await client.post("/events/telegram", json=_msg(301001, -301001, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -301001})
    await client.post(
        "/events/telegram",
        json=_msg(301002, -301001, text="/kb_ask hello", message_id=2, from_user_id=77),
    )
    await run_control_commands_cycle(
        session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1))
    )
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED


@pytest.mark.asyncio
async def test_kb_ask_replies_only_to_control_group_chat(k10e_client, monkeypatch):
    _env10e(monkeypatch)
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK10e")
    get_settings.cache_clear()

    async def fake_chat(settings, *, system_prompt: str, user_prompt: str) -> str:
        return "cg reply ok"

    monkeypatch.setattr("pb_studio.knowledge.rag._openai_compatible_chat", fake_chat)

    client, session = k10e_client
    h = {"Authorization": "Bearer adm10e"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "CG", "status": "draft"})
    await client.post(
        f"/knowledge/documents/{d.json()['id']}/versions/text",
        headers=h,
        json={"text": "kb_ask_control_group_only_token", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)

    cg_tid = -302001
    await client.post("/events/telegram", json=_msg(302001, cg_tid, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg_tid})
    await client.post(
        "/events/telegram",
        json=_msg(302002, cg_tid, text="/kb_ask kb_ask_control_group_only_token", message_id=2),
    )
    send = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=send)
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.command_name == ControlCommandName.KB_ASK
    assert cmd.status == ControlCommandStatus.PROCESSED
    send.assert_awaited()
    assert send.await_args is not None
    assert send.await_args.kwargs["chat_id"] == cg_tid


@pytest.mark.asyncio
async def test_kb_ask_does_not_touch_response_queue_enqueue(k10e_client, monkeypatch):
    _env10e(monkeypatch)
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK10e")
    get_settings.cache_clear()

    async def fake_chat(settings, *, system_prompt: str, user_prompt: str) -> str:
        return "ok"

    monkeypatch.setattr("pb_studio.knowledge.rag._openai_compatible_chat", fake_chat)

    real_enqueue = QueueService.enqueue
    called = {"n": 0}

    async def guard_enqueue(self, session, payload, *, now=None):
        called["n"] += 1
        return await real_enqueue(self, session, payload, now=now)

    monkeypatch.setattr(QueueService, "enqueue", guard_enqueue)

    client, session = k10e_client
    h = {"Authorization": "Bearer adm10e"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "Q", "status": "draft"})
    await client.post(
        f"/knowledge/documents/{d.json()['id']}/versions/text",
        headers=h,
        json={"text": "queue_guard_kb_ask", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    cg_tid = -303001
    await client.post("/events/telegram", json=_msg(303001, cg_tid, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg_tid})
    await client.post(
        "/events/telegram",
        json=_msg(303002, cg_tid, text="/kb_ask queue_guard_kb_ask", message_id=2),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_kb_ask_no_real_httpx_when_chat_mocked(k10e_client, monkeypatch):
    _env10e(monkeypatch)
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK10e")
    get_settings.cache_clear()

    async def fake_chat(settings, *, system_prompt: str, user_prompt: str) -> str:
        return "stub"

    monkeypatch.setattr("pb_studio.knowledge.rag._openai_compatible_chat", fake_chat)

    def boom(*_a, **_k):
        raise AssertionError("httpx.AsyncClient")

    monkeypatch.setattr(httpx, "AsyncClient", boom)

    client, session = k10e_client
    h = {"Authorization": "Bearer adm10e"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "H", "status": "draft"})
    await client.post(
        f"/knowledge/documents/{d.json()['id']}/versions/text",
        headers=h,
        json={"text": "httpx guard kb_ask", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    cg_tid = -304001
    await client.post("/events/telegram", json=_msg(304001, cg_tid, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg_tid})
    await client.post(
        "/events/telegram",
        json=_msg(304002, cg_tid, text="/kb_ask httpx", message_id=2),
    )
    await run_control_commands_cycle(
        session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1))
    )
