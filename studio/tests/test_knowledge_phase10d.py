"""Фаза 10d: внешний embedding provider (OpenAI-compatible) + deterministic."""

from __future__ import annotations

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
from pb_studio.core.config import get_settings
from pb_studio.knowledge.constants import (
    KNOWLEDGE_EMBEDDING_VECTOR_DIM,
    KnowledgeChunkEmbeddingStatus,
    KnowledgeEmbeddingProviderKind,
)
from pb_studio.knowledge.embeddings import (
    DeterministicEmbeddingProvider,
    OpenaiCompatibleEmbeddingProvider,
    deterministic_unit_vector,
    get_embedding_provider,
    redact_embedding_error,
)
from pb_studio.knowledge.models import StudioKnowledgeChunk, StudioKnowledgeDocumentVersion
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def kd_engine():
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
async def kd_client(kd_engine):
    factory = async_sessionmaker(kd_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env_kb_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10d")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "400")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "10")
    get_settings.cache_clear()


def test_get_embedding_provider_default_is_deterministic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("STUDIO_KB_EMBEDDING_PROVIDER", raising=False)
    get_settings.cache_clear()
    p = get_embedding_provider(get_settings())
    assert isinstance(p, DeterministicEmbeddingProvider)
    assert p.batch_atomic is False


def test_redact_embedding_error_removes_api_key():
    key = "sk-test-secret-key-12345"
    msg = f"HTTP 401 invalid bearer {key} tail"
    out = redact_embedding_error(msg, key)
    assert key not in out


@pytest.mark.asyncio
async def test_openai_compatible_stub_embeds_without_real_http(kd_client, monkeypatch):
    _env_kb_embed(monkeypatch)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_PROVIDER", KnowledgeEmbeddingProviderKind.OPENAI_COMPATIBLE)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_KEY", "sk-dummy")
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_MODEL", "test-model")
    get_settings.cache_clear()

    async def stub_embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [deterministic_unit_vector(t, KNOWLEDGE_EMBEDDING_VECTOR_DIM) for t in texts]

    monkeypatch.setattr(OpenaiCompatibleEmbeddingProvider, "embed_texts", stub_embed_texts)

    client, session = kd_client
    h = {"Authorization": "Bearer adm10d"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "OAI", "status": "draft"})
    doc_id = UUID(d.json()["id"])
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "hello openai stub path", "defer_parse": False},
    )
    r = await client.post("/knowledge/embed-pending", headers=h)
    assert r.status_code == 200
    assert r.json()["embedded"] >= 1
    ver = await session.scalar(
        select(StudioKnowledgeDocumentVersion).where(StudioKnowledgeDocumentVersion.document_id == doc_id)
    )
    assert ver is not None
    ch = await session.scalar(select(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == ver.id))
    assert ch is not None
    assert ch.embedding_status == KnowledgeChunkEmbeddingStatus.EMBEDDED
    assert ch.embedding_model == "test-model"


@pytest.mark.asyncio
async def test_openai_error_does_not_leak_api_key_into_last_error(kd_client, monkeypatch):
    _env_kb_embed(monkeypatch)
    secret = "sk-leak-test-unique-xyz"
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_PROVIDER", KnowledgeEmbeddingProviderKind.OPENAI_COMPATIBLE)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_KEY", secret)
    get_settings.cache_clear()

    async def boom(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError(f"embeddings HTTP 401: unauthorized token {secret}")

    monkeypatch.setattr(OpenaiCompatibleEmbeddingProvider, "embed_texts", boom)

    client, session = kd_client
    h = {"Authorization": "Bearer adm10d"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "Leak", "status": "draft"})
    doc_id = UUID(d.json()["id"])
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "x", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    ver = await session.scalar(
        select(StudioKnowledgeDocumentVersion).where(StudioKnowledgeDocumentVersion.document_id == doc_id)
    )
    assert ver is not None
    ch = await session.scalar(select(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == ver.id))
    assert ch is not None
    assert ch.embedding_status == KnowledgeChunkEmbeddingStatus.FAILED
    err = ch.embedding_last_error or ""
    assert secret not in err


@pytest.mark.asyncio
async def test_openai_batch_failure_does_not_stop_next_batch(kd_client, monkeypatch):
    _env_kb_embed(monkeypatch)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_PROVIDER", KnowledgeEmbeddingProviderKind.OPENAI_COMPATIBLE)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_KEY", "sk-x")
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_BATCH_SIZE", "2")
    get_settings.cache_clear()

    calls = {"n": 0}

    async def stub(self, texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("embeddings request timeout")
        return [deterministic_unit_vector(t, KNOWLEDGE_EMBEDDING_VECTOR_DIM) for t in texts]

    monkeypatch.setattr(OpenaiCompatibleEmbeddingProvider, "embed_texts", stub)

    client, session = kd_client
    h = {"Authorization": "Bearer adm10d"}
    for label in ("A", "B", "C", "D"):
        d = await client.post("/knowledge/documents", headers=h, json={"title": label, "status": "draft"})
        await client.post(
            f"/knowledge/documents/{d.json()['id']}/versions/text",
            headers=h,
            json={"text": f"body-{label}-unique", "defer_parse": False},
        )
    r = await client.post("/knowledge/embed-pending", headers=h)
    assert r.status_code == 200
    assert r.json()["failed"] >= 2
    assert r.json()["embedded"] >= 2


@pytest.mark.asyncio
async def test_embedded_chunks_not_reprocessed_openai_stub(kd_client, monkeypatch):
    _env_kb_embed(monkeypatch)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_PROVIDER", KnowledgeEmbeddingProviderKind.OPENAI_COMPATIBLE)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_KEY", "sk-x")
    get_settings.cache_clear()

    async def stub(self, texts: list[str]) -> list[list[float]]:
        return [deterministic_unit_vector(t, KNOWLEDGE_EMBEDDING_VECTOR_DIM) for t in texts]

    monkeypatch.setattr(OpenaiCompatibleEmbeddingProvider, "embed_texts", stub)

    client, _session = kd_client
    h = {"Authorization": "Bearer adm10d"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "R", "status": "draft"})
    doc_id = UUID(d.json()["id"])
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "stable", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    r2 = await client.post("/knowledge/embed-pending", headers=h)
    assert r2.json()["embedded"] == 0
    assert r2.json()["failed"] == 0


@pytest.mark.asyncio
async def test_openai_only_embeddings_url_called_not_chat(kd_client, monkeypatch):
    _env_kb_embed(monkeypatch)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_PROVIDER", KnowledgeEmbeddingProviderKind.OPENAI_COMPATIBLE)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_KEY", "sk-x")
    get_settings.cache_clear()

    seen: list[str] = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, **kwargs):
            seen.append(str(url))
            emb = [0.01] * KNOWLEDGE_EMBEDDING_VECTOR_DIM
            return httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": emb}]},
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    client, _session = kd_client
    h = {"Authorization": "Bearer adm10d"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "Http", "status": "draft"})
    await client.post(
        f"/knowledge/documents/{d.json()['id']}/versions/text",
        headers=h,
        json={"text": "one", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    assert seen and seen[0].endswith("/embeddings")
    assert "chat/completions" not in seen[0]


@pytest.mark.asyncio
async def test_kb_search_still_works_with_openai_stub(kd_client, monkeypatch):
    _env_kb_embed(monkeypatch)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_PROVIDER", KnowledgeEmbeddingProviderKind.OPENAI_COMPATIBLE)
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("STUDIO_KB_EMBEDDING_API_KEY", "sk-x")
    get_settings.cache_clear()

    async def stub(self, texts: list[str]) -> list[list[float]]:
        return [deterministic_unit_vector(t, KNOWLEDGE_EMBEDDING_VECTOR_DIM) for t in texts]

    monkeypatch.setattr(OpenaiCompatibleEmbeddingProvider, "embed_texts", stub)

    client, _session = kd_client
    h = {"Authorization": "Bearer adm10d"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "S", "status": "draft"})
    await client.post(
        f"/knowledge/documents/{d.json()['id']}/versions/text",
        headers=h,
        json={"text": "unique zzyyaa token search", "defer_parse": False},
    )
    await client.post("/knowledge/embed-pending", headers=h)
    s = await client.post("/knowledge/search", headers=h, json={"query": "zzyyaa"})
    assert s.status_code == 200
    assert len(s.json()) >= 1
