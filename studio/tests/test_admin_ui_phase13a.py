"""Фаза 13a: Studio Admin UI skeleton (read-only /admin/*, STUDIO_ADMIN_TOKEN)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pb_studio.assistant_rules.models  # noqa: F401
import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.history_import.models  # noqa: F401
import pb_studio.knowledge.models  # noqa: F401
import pb_studio.project_digests.models  # noqa: F401
import pb_studio.projects.models  # noqa: F401
import pb_studio.sla.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.core.config import get_settings
from pb_studio.response_queue.service import create_tables


ADMIN_UI_TOKEN = "phase13a-admin-ui-test-token-secret-unique-Z9k"


@pytest_asyncio.fixture
async def a13_engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await create_tables(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def a13_client(a13_engine):
    factory = async_sessionmaker(a13_engine, class_=AsyncSession, expire_on_commit=False)
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
            yield client
        app.dependency_overrides.clear()


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_UI_TOKEN}"}


@pytest.mark.asyncio
async def test_admin_dashboard_requires_token_configured(a13_client, monkeypatch):
    monkeypatch.delenv("STUDIO_ADMIN_TOKEN", raising=False)
    get_settings.cache_clear()
    r = await a13_client.get("/admin/")
    assert r.status_code == 503
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_without_credentials_redirects_to_login(a13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    r = await a13_client.get("/admin/", follow_redirects=False)
    assert r.status_code == 302
    assert "/admin/login" in (r.headers.get("location") or "")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_without_credentials_json_accept_returns_401(a13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    r = await a13_client.get("/admin/", headers={"Accept": "application/json"})
    assert r.status_code == 401
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_with_bearer_opens_dashboard(a13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    r = await a13_client.get("/admin/", headers=_auth_headers())
    assert r.status_code == 200
    assert "Обзор" in r.text
    assert ADMIN_UI_TOKEN not in r.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_section_pages_200_with_bearer(a13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    h = _auth_headers()
    paths = (
        "/admin/",
        "/admin/chats",
        "/admin/control-group",
        "/admin/summaries",
        "/admin/projects",
        "/admin/sla/incidents",
        "/admin/knowledge/documents",
        "/admin/assistant-rules",
        "/admin/history-import/jobs",
    )
    for path in paths:
        resp = await a13_client.get(path, headers=h)
        assert resp.status_code == 200, f"{path}: {resp.status_code}"
        assert ADMIN_UI_TOKEN not in resp.text, path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_slash_redirect(a13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    r = await a13_client.get("/admin", follow_redirects=False, headers=_auth_headers())
    assert r.status_code == 302
    loc = r.headers.get("location") or ""
    assert loc.endswith("/admin/") or loc.rstrip("/").endswith("/admin")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_login_get_ok_when_token_set(a13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    r = await a13_client.get("/admin/login")
    assert r.status_code == 200
    assert ADMIN_UI_TOKEN not in r.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_wrong_bearer_401(a13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    r = await a13_client.get("/admin/", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_health_unaffected(a13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    r = await a13_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    get_settings.cache_clear()
