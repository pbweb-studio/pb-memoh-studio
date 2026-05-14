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
from pb_studio.knowledge.constants import (
    KNOWLEDGE_EMBEDDING_VECTOR_DIM,
    KnowledgeChunkEmbeddingStatus,
)
from pb_studio.knowledge.embeddings import DeterministicEmbeddingProvider
from pb_studio.knowledge.models import (
    StudioKnowledgeChunk,
    StudioKnowledgeDocumentVersion,
)
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def kc10_engine():
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
async def kc10_client(kc10_engine):
    factory = async_sessionmaker(kc10_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env10c(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10c")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "500")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "10")
    monkeypatch.setenv("STUDIO_KB_SEARCH_TOP_K", "5")
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
async def test_chunks_receive_embeddings(kc10_client, monkeypatch):
    _env10c(monkeypatch)
    client, session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "E1", "status": "draft"})
    doc_id = UUID(d.json()["id"])
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "hello world unique alpha", "defer_parse": False},
    )
    r = await client.post("/knowledge/embed-pending", headers=h)
    assert r.status_code == 200
    assert r.json()["embedded"] >= 1
    assert r.json()["failed"] == 0
    ver = await session.scalar(
        select(StudioKnowledgeDocumentVersion).where(StudioKnowledgeDocumentVersion.document_id == doc_id)
    )
    assert ver is not None
    row = await session.scalar(
        select(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == ver.id).limit(1)
    )
    assert row is not None
    assert row.embedding_status == KnowledgeChunkEmbeddingStatus.EMBEDDED
    assert row.embedding is not None
    assert len(row.embedding) == KNOWLEDGE_EMBEDDING_VECTOR_DIM


@pytest.mark.asyncio
async def test_repeat_embed_no_duplicate_vectors(kc10_client, monkeypatch):
    _env10c(monkeypatch)
    client, session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "E2", "status": "draft"})
    doc_id = UUID(d.json()["id"])
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "stable text for embed idempotency", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    ver = await session.scalar(
        select(StudioKnowledgeDocumentVersion).where(StudioKnowledgeDocumentVersion.document_id == doc_id)
    )
    assert ver is not None
    ch = await session.scalar(select(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == ver.id))
    assert ch is not None
    first_vec = list(ch.embedding or [])
    r2 = await client.post("/knowledge/embed-pending", headers=h)
    assert r2.status_code == 200
    assert r2.json()["embedded"] == 0
    await session.refresh(ch)
    assert list(ch.embedding or []) == first_vec


@pytest.mark.asyncio
async def test_failed_chunk_does_not_stop_batch(kc10_client, monkeypatch):
    _env10c(monkeypatch)

    class BoomProvider(DeterministicEmbeddingProvider):
        async def embed_one(self, text: str) -> list[float]:
            if "BOOM_CHUNK" in text:
                raise RuntimeError("simulated embed failure")
            return await super().embed_one(text)

    monkeypatch.setattr("pb_studio.knowledge.service.get_embedding_provider", lambda _s: BoomProvider())
    get_settings.cache_clear()

    client, session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    d_bad = await client.post("/knowledge/documents", headers=h, json={"title": "E3bad", "status": "draft"})
    d_ok = await client.post("/knowledge/documents", headers=h, json={"title": "E3ok", "status": "draft"})
    await client.post(
        f"/knowledge/documents/{d_bad.json()['id']}/versions/text",
        headers=h,
        json={"text": "prefix BOOM_CHUNK suffix in one chunk", "defer_parse": False},
    )
    await client.post(
        f"/knowledge/documents/{d_ok.json()['id']}/versions/text",
        headers=h,
        json={"text": "safe unique ok text for embed batch", "defer_parse": False},
    )
    r = await client.post("/knowledge/embed-pending", headers=h)
    assert r.status_code == 200
    assert r.json()["embedded"] >= 1
    assert r.json()["failed"] >= 1
    n_emb = await session.scalar(
        select(func.count()).select_from(StudioKnowledgeChunk).where(
            StudioKnowledgeChunk.embedding_status == KnowledgeChunkEmbeddingStatus.EMBEDDED
        )
    )
    n_fail = await session.scalar(
        select(func.count()).select_from(StudioKnowledgeChunk).where(
            StudioKnowledgeChunk.embedding_status == KnowledgeChunkEmbeddingStatus.FAILED
        )
    )
    assert int(n_emb or 0) >= 1
    assert int(n_fail or 0) >= 1


@pytest.mark.asyncio
async def test_search_returns_top_k(kc10_client, monkeypatch):
    _env10c(monkeypatch)
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "40")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "0")
    get_settings.cache_clear()
    client, _session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "Many", "status": "draft"})
    doc_id = d.json()["id"]
    long_text = " ".join([f"segment-{idx}-words" for idx in range(30)])
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": long_text, "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    s = await client.post("/knowledge/search", headers=h, json={"query": "segment-5", "top_k": 3})
    assert s.status_code == 200
    hits = s.json()
    assert len(hits) <= 3
    assert len(hits) >= 1


@pytest.mark.asyncio
async def test_search_filters_by_project_id(kc10_client, monkeypatch):
    _env10c(monkeypatch)
    client, _session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    p = await client.post("/projects", headers=h, json={"slug": "kbp1", "name": "KB P1"})
    assert p.status_code == 200
    pid = UUID(p.json()["id"])
    d1 = await client.post("/knowledge/documents", headers=h, json={"title": "InProj", "project_id": str(pid)})
    d2 = await client.post("/knowledge/documents", headers=h, json={"title": "NoProj", "project_id": None})
    id1 = d1.json()["id"]
    await client.post(
        f"/knowledge/documents/{id1}/versions/text",
        headers=h,
        json={"text": "unique_project_alpha_token_xyz", "defer_parse": False},
    )
    await client.post(
        f"/knowledge/documents/{d2.json()['id']}/versions/text",
        headers=h,
        json={"text": "unique_project_alpha_token_xyz duplicate surface", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    s = await client.post(
        "/knowledge/search",
        headers=h,
        json={"query": "unique_project_alpha_token_xyz", "project_id": str(pid), "top_k": 10},
    )
    assert s.status_code == 200
    hits = s.json()
    assert hits
    for hit in hits:
        assert hit["document_id"] == id1


@pytest.mark.asyncio
async def test_embed_search_api_requires_admin(kc10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "x")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    get_settings.cache_clear()
    client, _session = kc10_client
    r = await client.post("/knowledge/embed-pending")
    assert r.status_code == 401
    s = await client.post("/knowledge/search", json={"query": "a"})
    assert s.status_code == 401


@pytest.mark.asyncio
async def test_embed_search_requires_embeddings_flag(kc10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10c")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "false")
    get_settings.cache_clear()
    client, _session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    r = await client.post("/knowledge/embed-pending", headers=h)
    assert r.status_code == 503
    s = await client.post("/knowledge/search", headers=h, json={"query": "hello"})
    assert s.status_code == 503


@pytest.mark.asyncio
async def test_kb_search_control_group_acl(kc10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10c")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    get_settings.cache_clear()

    client, session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    await client.post("/events/telegram", json=_msg(201001, -201001, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -201001})
    await client.post(
        "/events/telegram",
        json=_msg(201002, -201001, text="/kb_search hello world", message_id=2, from_user_id=99),
    )
    await run_control_commands_cycle(
        session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1))
    )
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd is not None
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED


@pytest.mark.asyncio
async def test_kb_search_runs_in_control_group(kc10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10c")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    get_settings.cache_clear()

    client, session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "S", "status": "draft"})
    doc_id = d.json()["id"]
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "kbsearch unique token zzyy", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)

    await client.post("/events/telegram", json=_msg(202001, -202001, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -202001})
    await client.post(
        "/events/telegram",
        json=_msg(202002, -202001, text="/kb_search zzyy", message_id=2, from_user_id=42),
    )
    send = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=send)
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.command_name == ControlCommandName.KB_SEARCH
    assert cmd.status == ControlCommandStatus.PROCESSED
    send.assert_awaited()


@pytest.mark.asyncio
async def test_kb_search_no_httpx_when_send_mocked(kc10_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10c")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    get_settings.cache_clear()

    def boom(*_a, **_k):
        raise AssertionError("httpx")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    client, session = kc10_client
    h = {"Authorization": "Bearer adm10c"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "S", "status": "draft"})
    doc_id = d.json()["id"]
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "httpx guard kbsearch", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    await client.post("/events/telegram", json=_msg(203001, -203001, text="x"))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -203001})
    await client.post(
        "/events/telegram",
        json=_msg(203002, -203001, text="/kb_search httpx", message_id=2),
    )
    await run_control_commands_cycle(
        session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1))
    )


def test_celery_registers_embed_pending_knowledge():
    assert "pb_studio.worker.embed_pending_knowledge_chunks" in celery_app.tasks
