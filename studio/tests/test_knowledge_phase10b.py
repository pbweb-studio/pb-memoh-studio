from __future__ import annotations

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
import pb_studio.knowledge.models  # noqa: F401
import pb_studio.project_digests.models  # noqa: F401
import pb_studio.projects.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
import pb_studio.worker.tasks  # noqa: F401 - register Celery tasks
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.celery_app import celery_app
from pb_studio.control_commands.constants import ControlCommandName, ControlCommandStatus
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.control_commands.service import run_control_commands_cycle
from pb_studio.core.config import get_settings
from pb_studio.knowledge.constants import KnowledgeVersionStatus
from pb_studio.knowledge.models import StudioKnowledgeChunk, StudioKnowledgeDocumentVersion
from pb_studio.knowledge.service import parse_pending_knowledge_versions_batch
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def kb10_engine():
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
async def kb10_client(kb10_engine):
    factory = async_sessionmaker(kb10_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env10b(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10b")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "120")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "10")
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
async def test_pending_version_parses_to_chunks(kb10_client, monkeypatch):
    _env10b(monkeypatch)
    client, _session = kb10_client
    h = {"Authorization": "Bearer adm10b"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "P1", "status": "draft"})
    doc_id = d.json()["id"]
    v = await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={
            "text": "z" * 400,
            "defer_parse": True,
            "metadata_json": {"mime_type": "text/markdown"},
        },
    )
    assert v.status_code == 200
    assert v.json()["status"] == KnowledgeVersionStatus.PENDING
    vid = v.json()["id"]
    p = await client.post(f"/knowledge/documents/{doc_id}/parse", headers=h)
    assert p.status_code == 200
    assert p.json()["parsed"] == 1
    assert p.json()["failed"] == 0
    ch = await client.get(f"/knowledge/versions/{vid}/chunks", headers=h)
    assert len(ch.json()) >= 2


@pytest.mark.asyncio
async def test_unsupported_mime_marks_failed_without_batch_crash(kb10_client, monkeypatch):
    _env10b(monkeypatch)
    client, session = kb10_client
    h = {"Authorization": "Bearer adm10b"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "PdfDoc", "source_type": "file"})
    doc_id = d.json()["id"]
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "", "defer_parse": True, "metadata_json": {"mime_type": "application/pdf"}},
    )
    d2 = await client.post("/knowledge/documents", headers=h, json={"title": "OkDoc", "status": "draft"})
    doc2 = d2.json()["id"]
    r2 = await client.post(
        f"/knowledge/documents/{doc2}/versions/text",
        headers=h,
        json={"text": "okbody", "defer_parse": True, "metadata_json": {"mime_type": "text/plain"}},
    )
    vid2 = r2.json()["id"]

    out = await parse_pending_knowledge_versions_batch(session, get_settings(), limit=20)
    await session.commit()
    assert out["parsed"] >= 1
    assert out["failed"] >= 1

    v_pdf = await session.scalar(
        select(StudioKnowledgeDocumentVersion).where(StudioKnowledgeDocumentVersion.document_id == UUID(doc_id))
    )
    assert v_pdf is not None
    assert v_pdf.status == KnowledgeVersionStatus.FAILED_UNSUPPORTED

    v_ok = await session.get(StudioKnowledgeDocumentVersion, UUID(vid2))
    assert v_ok is not None
    assert v_ok.status == KnowledgeVersionStatus.PARSED


@pytest.mark.asyncio
async def test_double_parse_no_extra_chunks(kb10_client, monkeypatch):
    _env10b(monkeypatch)
    client, session = kb10_client
    h = {"Authorization": "Bearer adm10b"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "D2", "status": "draft"})
    doc_id = d.json()["id"]
    v = await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "abc" * 100, "defer_parse": True},
    )
    vid = v.json()["id"]
    await client.post(f"/knowledge/documents/{doc_id}/parse", headers=h)
    c1 = await session.scalar(
        select(func.count()).select_from(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == UUID(vid))
    )
    await client.post(f"/knowledge/documents/{doc_id}/parse", headers=h)
    c2 = await session.scalar(
        select(func.count()).select_from(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == UUID(vid))
    )
    assert int(c1 or 0) == int(c2 or 0)


@pytest.mark.asyncio
async def test_parse_api_requires_admin(kb10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "x")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    get_settings.cache_clear()
    client, _session = kb10_client
    r = await client.post("/knowledge/parse-pending")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_kb_parse_from_control_group(kb10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10b")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    get_settings.cache_clear()

    client, session = kb10_client
    h = {"Authorization": "Bearer adm10b"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "C", "status": "draft"})
    doc_id = d.json()["id"]
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "qqq", "defer_parse": True},
    )

    await client.post("/events/telegram", json=_msg(101001, -101001, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -101001})
    await client.post(
        "/events/telegram",
        json=_msg(101002, -101001, text=f"/kb_parse {doc_id}", message_id=2),
    )
    await run_control_commands_cycle(
        session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1))
    )
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.command_name == ControlCommandName.KB_PARSE
    assert cmd.status == ControlCommandStatus.PROCESSED


@pytest.mark.asyncio
async def test_kb_parse_acl_denied(kb10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10b")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    get_settings.cache_clear()

    client, session = kb10_client
    h = {"Authorization": "Bearer adm10b"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "C", "status": "draft"})
    doc_id = d.json()["id"]
    await client.post("/events/telegram", json=_msg(102001, -102001, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -102001})
    await client.post(
        "/events/telegram",
        json=_msg(102002, -102001, text=f"/kb_parse {doc_id}", message_id=2, from_user_id=99),
    )
    await run_control_commands_cycle(
        session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1))
    )
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED


@pytest.mark.asyncio
async def test_kb_parse_no_httpx_when_send_mocked(kb10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10b")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    get_settings.cache_clear()

    def boom(*_a, **_k):
        raise AssertionError("httpx")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    client, session = kb10_client
    h = {"Authorization": "Bearer adm10b"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "C", "status": "draft"})
    doc_id = d.json()["id"]
    await client.post("/events/telegram", json=_msg(103001, -103001, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -103001})
    await client.post(
        "/events/telegram",
        json=_msg(103002, -103001, text=f"/kb_parse {doc_id}", message_id=2),
    )
    await run_control_commands_cycle(
        session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1))
    )


@pytest.mark.asyncio
async def test_kb_list_not_created_outside_control_group(kb10_client, monkeypatch):
    """Regression: /kb_parse only from CG (mirror scan)."""
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10b")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    get_settings.cache_clear()
    client, session = kb10_client
    h = {"Authorization": "Bearer adm10b"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "C", "status": "draft"})
    doc_id = d.json()["id"]
    await client.post("/events/telegram", json=_msg(104001, -104001, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -104001})
    await client.post(
        "/events/telegram",
        json=_msg(104002, -104002, text=f"/kb_parse {doc_id}", message_id=2),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    assert list((await session.scalars(select(StudioControlCommand))).all()) == []


def test_celery_registers_parse_pending_knowledge():
    assert "pb_studio.worker.parse_pending_knowledge_documents" in celery_app.tasks
