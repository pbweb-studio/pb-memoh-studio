"""Фаза 12a: импорт Telegram Desktop JSON → Event Mirror (без Memoh / Bot API)."""

from __future__ import annotations

import json
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
import pb_studio.history_import.models  # noqa: F401
import pb_studio.knowledge.models  # noqa: F401
import pb_studio.project_digests.models  # noqa: F401
import pb_studio.projects.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.history_import.constants import HistoryImportJobStatus
from pb_studio.history_import.models import StudioHistoryImportJob
from pb_studio.response_queue.models import Base


def _sample_export() -> bytes:
    doc = {
        "id": -100999888777,
        "name": "Phase12a Import Chat",
        "type": "supergroup",
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2020-01-02T12:00:00",
                "from": "Alice",
                "from_id": "user100001",
                "text": "hello_phase12a",
            },
            {
                "id": 2,
                "type": "message",
                "date": "2020-01-02T12:01:00",
                "from": "Bob",
                "from_id": "user100002",
                "text": "world_phase12a",
            },
            {"type": "unknown_shape_no_id"},
            {
                "id": 3,
                "type": "message",
                "date": "not-a-date",
                "text": "bad date row",
            },
            {
                "id": 4,
                "type": "service",
                "date": "2020-01-02T13:00:00",
                "action": "create_group",
                "actor": "Sys",
                "actor_id": "user100001",
            },
        ],
    }
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


@pytest_asyncio.fixture
async def h12_engine():
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
async def h12_client(h12_engine):
    factory = async_sessionmaker(h12_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env12(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm12")
    monkeypatch.setenv("STUDIO_HISTORY_IMPORT_ENABLED", "true")
    monkeypatch.setenv("STUDIO_HISTORY_IMPORT_MAX_BYTES", "52428800")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_telegram_json_import_creates_chat_and_messages(h12_client, monkeypatch):
    _env12(monkeypatch)
    client, session = h12_client
    h = {"Authorization": "Bearer adm12"}
    body = _sample_export()
    r = await client.post(
        "/history-import/telegram-json",
        headers=h,
        files={"file": ("export.json", body, "application/json")},
    )
    assert r.status_code == 201, r.text
    job = r.json()["job"]
    assert job["status"] == HistoryImportJobStatus.COMPLETED
    assert job["imported_chat_count"] == 1
    assert job["imported_message_count"] == 2
    assert job["skipped_count"] >= 2

    n_chats = await session.scalar(select(func.count()).select_from(StudioChat))
    assert int(n_chats or 0) == 1
    ch = await session.scalar(select(StudioChat))
    assert ch is not None
    assert ch.telegram_chat_id == -100999888777

    n_msg = await session.scalar(select(func.count()).select_from(StudioMessage))
    assert int(n_msg or 0) == 2


@pytest.mark.asyncio
async def test_second_import_does_not_duplicate_messages(h12_client, monkeypatch):
    _env12(monkeypatch)
    client, session = h12_client
    h = {"Authorization": "Bearer adm12"}
    body = _sample_export()
    await client.post("/history-import/telegram-json", headers=h, files={"file": ("a.json", body, "application/json")})
    r2 = await client.post(
        "/history-import/telegram-json",
        headers=h,
        files={"file": ("b.json", body, "application/json")},
    )
    assert r2.status_code == 201
    job2 = r2.json()["job"]
    assert job2["imported_message_count"] == 0
    n_msg = await session.scalar(select(func.count()).select_from(StudioMessage))
    assert int(n_msg or 0) == 2


@pytest.mark.asyncio
async def test_oversized_file_rejected(h12_client, monkeypatch):
    _env12(monkeypatch)
    monkeypatch.setenv("STUDIO_HISTORY_IMPORT_MAX_BYTES", "64")
    get_settings.cache_clear()
    client, _ = h12_client
    h = {"Authorization": "Bearer adm12"}
    r = await client.post(
        "/history-import/telegram-json",
        headers=h,
        files={"file": ("big.json", b"x" * 200, "application/json")},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_import_disabled_returns_503(h12_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm12")
    monkeypatch.setenv("STUDIO_HISTORY_IMPORT_ENABLED", "false")
    get_settings.cache_clear()
    client, _ = h12_client
    h = {"Authorization": "Bearer adm12"}
    r = await client.post(
        "/history-import/telegram-json",
        headers=h,
        files={"file": ("x.json", _sample_export(), "application/json")},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_import_requires_admin_token(h12_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "secret12")
    monkeypatch.setenv("STUDIO_HISTORY_IMPORT_ENABLED", "true")
    get_settings.cache_clear()
    client, _ = h12_client
    r = await client.post(
        "/history-import/telegram-json",
        files={"file": ("x.json", _sample_export(), "application/json")},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_job_and_list_jobs(h12_client, monkeypatch):
    _env12(monkeypatch)
    client, _ = h12_client
    h = {"Authorization": "Bearer adm12"}
    r1 = await client.post(
        "/history-import/telegram-json",
        headers=h,
        files={"file": ("e.json", _sample_export(), "application/json")},
    )
    jid = r1.json()["job"]["id"]
    rj = await client.get(f"/history-import/jobs/{jid}", headers=h)
    assert rj.status_code == 200
    assert rj.json()["id"] == jid
    rl = await client.get("/history-import/jobs", headers=h)
    assert rl.status_code == 200
    assert len(rl.json()) >= 1


@pytest.mark.asyncio
async def test_invalid_json_creates_failed_job(h12_client, monkeypatch):
    _env12(monkeypatch)
    client, session = h12_client
    h = {"Authorization": "Bearer adm12"}
    r = await client.post(
        "/history-import/telegram-json",
        headers=h,
        files={"file": ("bad.json", b"not json {", "application/json")},
    )
    assert r.status_code == 201
    job = r.json()["job"]
    assert job["status"] == HistoryImportJobStatus.FAILED
    assert job["last_error"]

    row = await session.get(StudioHistoryImportJob, UUID(job["id"]))
    assert row is not None
    assert row.status == HistoryImportJobStatus.FAILED
