"""Фаза 13c: Studio Admin UI polish (filters, pagination, layout helpers)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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
from pb_studio.control_group.constants import ChatRole
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import StudioChat
from pb_studio.response_queue.service import create_tables

ADMIN_UI_TOKEN = "phase13c-admin-ui-test-token-secret-unique-Z9k"


@pytest_asyncio.fixture
async def c13_engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await create_tables(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def c13_client(c13_engine):
    factory = async_sessionmaker(c13_engine, class_=AsyncSession, expire_on_commit=False)
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


def _h() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_UI_TOKEN}"}


@pytest.mark.asyncio
async def test_list_pages_200(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, _ = c13_client
    for path in (
        "/admin/chats",
        "/admin/summaries",
        "/admin/projects",
        "/admin/sla/incidents",
        "/admin/knowledge/documents",
        "/admin/assistant-rules",
        "/admin/history-import/jobs",
    ):
        r = await client.get(path, headers=_h())
        assert r.status_code == 200, path
        assert ADMIN_UI_TOKEN not in r.text, path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chats_filter_by_role(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    session.add_all(
        [
            StudioChat(
                telegram_chat_id=-501,
                chat_type="supergroup",
                title="alpha client",
                chat_role=ChatRole.CLIENT_CHAT.value,
            ),
            StudioChat(
                telegram_chat_id=-502,
                chat_type="supergroup",
                title="beta internal",
                chat_role=ChatRole.INTERNAL_CHAT.value,
            ),
        ]
    )
    await session.commit()
    r = await client.get("/admin/chats", params={"role": ChatRole.CLIENT_CHAT.value}, headers=_h())
    assert r.status_code == 200
    assert "alpha client" in r.text
    assert "beta internal" not in r.text
    assert ADMIN_UI_TOKEN not in r.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chats_title_search(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    session.add(
        StudioChat(
            telegram_chat_id=-601,
            chat_type="supergroup",
            title="unique-xyz-title-13c",
            chat_role=ChatRole.UNKNOWN.value,
        )
    )
    await session.commit()
    r = await client.get("/admin/chats", params={"q": "unique-xyz"}, headers=_h())
    assert r.status_code == 200
    assert "unique-xyz-title-13c" in r.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chats_pagination_distinct_pages(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    for index in range(28):
        session.add(
            StudioChat(
                telegram_chat_id=-700 - index,
                chat_type="supergroup",
                title=f"pag-chat-{index}",
                chat_role=ChatRole.UNKNOWN.value,
            )
        )
    await session.commit()
    r1 = await client.get("/admin/chats", params={"page": 1, "limit": 10}, headers=_h())
    r2 = await client.get("/admin/chats", params={"page": 2, "limit": 10}, headers=_h())
    assert r1.status_code == 200 and r2.status_code == 200
    assert "pag-chat-0" in r1.text or "pag-chat-27" in r1.text
    assert r1.text != r2.text
    assert "Всего записей:" in r1.text
    assert "Вперёд →" in r1.text or "← Назад" in r2.text
    assert ADMIN_UI_TOKEN not in r1.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_projects_filter_active(c13_client, monkeypatch):
    from pb_studio.projects.models import StudioProject

    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    session.add_all(
        [
            StudioProject(slug="c13a", name="Active P", description=None, status="active"),
            StudioProject(slug="c13b", name="Archived P", description=None, status="archived"),
        ]
    )
    await session.commit()
    r = await client.get("/admin/projects", params={"status": "active"}, headers=_h())
    assert r.status_code == 200
    assert "Active P" in r.text
    assert "Archived P" not in r.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_token_not_in_query_pagination_links(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    for index in range(15):
        session.add(
            StudioChat(
                telegram_chat_id=-800 - index,
                chat_type="supergroup",
                title=f"tok-{index}",
                chat_role=ChatRole.UNKNOWN.value,
            )
        )
    await session.commit()
    r = await client.get("/admin/chats", params={"page": 1, "limit": 5}, headers=_h())
    assert r.status_code == 200
    assert ADMIN_UI_TOKEN not in r.text
    assert "page=2" in r.text
    get_settings.cache_clear()
