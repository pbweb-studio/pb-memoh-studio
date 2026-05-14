"""Фаза 10f: HTTP upload импорт в KB (txt/md/pdf/docx), опционально Docling."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

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
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.core.config import get_settings
from pb_studio.knowledge.constants import KnowledgeVersionStatus
from pb_studio.knowledge.models import StudioKnowledgeChunk, StudioKnowledgeDocumentVersion
from pb_studio.knowledge.service import parse_pending_knowledge_versions_batch
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def kf_engine():
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
async def kf_client(kf_engine):
    factory = async_sessionmaker(kf_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env10f(monkeypatch: pytest.MonkeyPatch, storage: Path) -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10f")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "200")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "10")
    monkeypatch.setenv("STUDIO_KB_UPLOAD_MAX_BYTES", "50000")
    monkeypatch.setenv("STUDIO_KB_ALLOWED_EXTENSIONS", "txt,md,pdf,docx")
    monkeypatch.setenv("STUDIO_KB_STORAGE_DIR", str(storage))
    monkeypatch.setenv("STUDIO_KB_DOCLING_ENABLED", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_upload_txt_creates_document_version_chunks(kf_client, monkeypatch, tmp_path):
    store = tmp_path / "kb"
    store.mkdir()
    _env10f(monkeypatch, store)
    client, session = kf_client
    h = {"Authorization": "Bearer adm10f"}
    r = await client.post(
        "/knowledge/documents/upload",
        headers=h,
        files={"file": ("note10f.txt", b"phase10f hello world unique content", "text/plain")},
        data={"title": "FromTxt"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["document"]["title"] == "FromTxt"
    assert body["version"]["status"] == KnowledgeVersionStatus.PARSED
    vid = UUID(body["version"]["id"])
    n = await session.scalar(select(func.count()).select_from(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == vid))
    assert int(n or 0) >= 1


@pytest.mark.asyncio
async def test_upload_md_creates_chunks(kf_client, monkeypatch, tmp_path):
    store = tmp_path / "kb2"
    store.mkdir()
    _env10f(monkeypatch, store)
    client, session = kf_client
    h = {"Authorization": "Bearer adm10f"}
    md = b"# Title\n\nphase10f md **bold** line\n"
    r = await client.post(
        "/knowledge/documents/upload",
        headers=h,
        files={"file": ("x.md", md, "text/markdown")},
    )
    assert r.status_code == 201
    vid = UUID(r.json()["version"]["id"])
    n = await session.scalar(select(func.count()).select_from(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == vid))
    assert int(n or 0) >= 1


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension(kf_client, monkeypatch, tmp_path):
    _env10f(monkeypatch, tmp_path / "kb3")
    (tmp_path / "kb3").mkdir(parents=True, exist_ok=True)
    client, _session = kf_client
    h = {"Authorization": "Bearer adm10f"}
    r = await client.post(
        "/knowledge/documents/upload",
        headers=h,
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_oversize(kf_client, monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10f")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "200")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "10")
    monkeypatch.setenv("STUDIO_KB_UPLOAD_MAX_BYTES", "100")
    monkeypatch.setenv("STUDIO_KB_ALLOWED_EXTENSIONS", "txt")
    monkeypatch.setenv("STUDIO_KB_STORAGE_DIR", str(tmp_path / "kb4"))
    (tmp_path / "kb4").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STUDIO_KB_DOCLING_ENABLED", "false")
    get_settings.cache_clear()
    client, _session = kf_client
    h = {"Authorization": "Bearer adm10f"}
    r = await client.post(
        "/knowledge/documents/upload",
        headers=h,
        files={"file": ("big.txt", b"x" * 200, "text/plain")},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_pdf_upload_docling_disabled_is_failed_unsupported(kf_client, monkeypatch, tmp_path):
    store = tmp_path / "kb5"
    store.mkdir()
    _env10f(monkeypatch, store)
    client, _session = kf_client
    h = {"Authorization": "Bearer adm10f"}
    pdf = b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    r = await client.post(
        "/knowledge/documents/upload",
        headers=h,
        files={"file": ("minimal.pdf", pdf, "application/pdf")},
    )
    assert r.status_code == 201
    assert r.json()["version"]["status"] == KnowledgeVersionStatus.FAILED_UNSUPPORTED


@pytest.mark.asyncio
async def test_parse_batch_one_pdf_one_txt(kf_client, monkeypatch, tmp_path):
    store = tmp_path / "kb6"
    store.mkdir()
    _env10f(monkeypatch, store)
    client, session = kf_client
    h = {"Authorization": "Bearer adm10f"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "Mix", "status": "draft"})
    doc_id = d.json()["id"]
    await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "", "defer_parse": True, "metadata_json": {"mime_type": "application/pdf"}},
    )
    d2 = await client.post("/knowledge/documents", headers=h, json={"title": "Ok2", "status": "draft"})
    doc2 = d2.json()["id"]
    await client.post(
        f"/knowledge/documents/{doc2}/versions/text",
        headers=h,
        json={"text": "okbody10f_batch", "defer_parse": True, "metadata_json": {"mime_type": "text/plain"}},
    )
    out = await parse_pending_knowledge_versions_batch(session, get_settings(), limit=20)
    await session.commit()
    assert out["parsed"] >= 1
    assert out["failed"] >= 1


@pytest.mark.asyncio
async def test_version_upload_endpoint(kf_client, monkeypatch, tmp_path):
    store = tmp_path / "kb7"
    store.mkdir()
    _env10f(monkeypatch, store)
    client, _session = kf_client
    h = {"Authorization": "Bearer adm10f"}
    d = await client.post("/knowledge/documents", headers=h, json={"title": "Base", "status": "draft"})
    doc_id = d.json()["id"]
    r = await client.post(
        f"/knowledge/documents/{doc_id}/versions/upload",
        headers=h,
        files={"file": ("v.txt", b"second version 10f", "text/plain")},
    )
    assert r.status_code == 201
    assert r.json()["version"]["version_number"] == 1
    assert r.json()["version"]["status"] == KnowledgeVersionStatus.PARSED


@pytest.mark.asyncio
async def test_upload_requires_admin(kf_client, monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "secret")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_STORAGE_DIR", str(tmp_path / "kb8"))
    (tmp_path / "kb8").mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()
    client, _session = kf_client
    r = await client.post(
        "/knowledge/documents/upload",
        files={"file": ("a.txt", b"hi", "text/plain")},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_parse_failed_outcome_redacts_api_key_pattern_in_last_error(kf_client, monkeypatch, tmp_path):
    store = tmp_path / "kb9"
    store.mkdir()
    _env10f(monkeypatch, store)
    client, session = kf_client
    h = {"Authorization": "Bearer adm10f"}
    secret = "sk-SECRETADM10FLEAK999"

    from pb_studio.knowledge.parsers import ParseOutcome

    def fake_parse(**_kwargs):
        return ParseOutcome(
            ok=False,
            plain_text="",
            parser_name="p",
            parser_version="v",
            unsupported=False,
            error_message=f"upstream {secret} done",
        )

    monkeypatch.setattr("pb_studio.knowledge.service.parse_document_version_content", fake_parse)

    d = await client.post("/knowledge/documents", headers=h, json={"title": "Red", "status": "draft"})
    doc_id = d.json()["id"]
    v = await client.post(
        f"/knowledge/documents/{doc_id}/versions/text",
        headers=h,
        json={"text": "body", "defer_parse": True},
    )
    vid = UUID(v.json()["id"])
    p = await client.post(f"/knowledge/documents/{doc_id}/parse", headers=h)
    assert p.status_code == 200
    row = await session.get(StudioKnowledgeDocumentVersion, vid)
    assert row is not None
    assert row.status == KnowledgeVersionStatus.FAILED
    assert secret not in (row.last_error or "")
