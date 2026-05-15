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
from uuid import uuid4

from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.models import StudioControlGroup
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


@pytest.mark.asyncio
async def test_control_group_page_empty_state_and_form(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    session.add(
        StudioChat(
            telegram_chat_id=-91001,
            chat_type="supergroup",
            title="cg-ui-empty-test",
            chat_role=ChatRole.UNKNOWN.value,
        )
    )
    await session.commit()
    r = await client.get("/admin/control-group", headers=_h())
    assert r.status_code == 200
    assert "Активная управляющая группа не назначена" in r.text
    assert 'name="telegram_chat_id"' in r.text
    assert "cg-ui-empty-test" in r.text
    assert ADMIN_UI_TOKEN not in r.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_control_group_set_creates_and_switches(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    cid_a = uuid4()
    cid_b = uuid4()
    session.add_all(
        [
            StudioChat(
                id=cid_a,
                telegram_chat_id=-92001,
                chat_type="supergroup",
                title="first-cg",
                chat_role=ChatRole.UNKNOWN.value,
            ),
            StudioChat(
                id=cid_b,
                telegram_chat_id=-92002,
                chat_type="supergroup",
                title="second-cg",
                chat_role=ChatRole.UNKNOWN.value,
            ),
        ]
    )
    await session.commit()
    r1 = await client.post(
        "/admin/control-group/set",
        data={"telegram_chat_id": "-92001", "redirect_to": "/admin/control-group"},
        headers=_h(),
        follow_redirects=False,
    )
    assert r1.status_code == 303
    active = await session.scalar(select(StudioControlGroup).where(StudioControlGroup.is_active.is_(True)))
    assert active is not None
    ch_a = await session.get(StudioChat, cid_a)
    assert ch_a is not None
    assert ch_a.chat_role == ChatRole.CONTROL_GROUP.value

    r2 = await client.post(
        "/admin/control-group/set",
        data={"telegram_chat_id": "-92002", "redirect_to": "/admin/control-group"},
        headers=_h(),
        follow_redirects=False,
    )
    assert r2.status_code == 303
    active2 = await session.scalar(select(StudioControlGroup).where(StudioControlGroup.is_active.is_(True)))
    assert active2 is not None
    assert active2.chat_id == cid_b
    ch_a2 = await session.get(StudioChat, cid_a)
    assert ch_a2 is not None
    assert ch_a2.chat_role == ChatRole.UNKNOWN.value
    ch_b2 = await session.get(StudioChat, cid_b)
    assert ch_b2 is not None
    assert ch_b2.chat_role == ChatRole.CONTROL_GROUP.value
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_detail_assign_control_group_button_visibility(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    gid = uuid4()
    pid = uuid4()
    session.add_all(
        [
            StudioChat(
                id=gid,
                telegram_chat_id=-93001,
                chat_type="supergroup",
                title="grp-btn",
                chat_role=ChatRole.UNKNOWN.value,
            ),
            StudioChat(
                id=pid,
                telegram_chat_id=93002,
                chat_type="private",
                title="priv-btn",
                chat_role=ChatRole.UNKNOWN.value,
            ),
        ]
    )
    await session.commit()
    rg = await client.get(f"/admin/chats/{gid}", headers=_h())
    assert rg.status_code == 200
    assert "Назначить управляющей группой" in rg.text
    rp = await client.get(f"/admin/chats/{pid}", headers=_h())
    assert rp.status_code == 200
    assert "Назначить управляющей группой" not in rp.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_detail_active_control_group_badge(c13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = c13_client
    cid = uuid4()
    session.add(
        StudioChat(
            id=cid,
            telegram_chat_id=-94001,
            chat_type="supergroup",
            title="active-badge",
            chat_role=ChatRole.UNKNOWN.value,
        )
    )
    await session.commit()
    await client.post(
        "/admin/control-group/set",
        data={"telegram_chat_id": "-94001", "redirect_to": "/admin/control-group"},
        headers=_h(),
        follow_redirects=False,
    )
    r = await client.get(f"/admin/chats/{cid}", headers=_h())
    assert r.status_code == 200
    assert "Активная управляющая группа" in r.text
    assert "Назначить управляющей группой" not in r.text
    get_settings.cache_clear()
