"""Фаза 13b: Studio Admin UI details + safe forms."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

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
from pb_studio.assistant_rules.constants import AssistantRuleScope, AssistantRuleSource, AssistantRuleStatus
from pb_studio.assistant_rules.models import StudioAssistantRule
from pb_studio.event_mirror.models import StudioChat
from pb_studio.knowledge.constants import KnowledgeDocumentStatus
from pb_studio.knowledge.models import StudioKnowledgeDocument
from pb_studio.projects.models import StudioProject
from pb_studio.response_queue.service import create_tables
from pb_studio.sla.constants import SlaIncidentStatus, SlaSeverity
from pb_studio.sla.models import StudioSlaIncident

ADMIN_UI_TOKEN = "phase13b-admin-ui-test-token-secret-unique-Z9k"


@pytest_asyncio.fixture
async def b13_engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await create_tables(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def b13_client(b13_engine):
    factory = async_sessionmaker(b13_engine, class_=AsyncSession, expire_on_commit=False)
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
async def test_detail_pages_200(b13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = b13_client
    now = datetime.now(timezone.utc)
    chat = StudioChat(
        telegram_chat_id=-100555444,
        chat_type="supergroup",
        title="b13 chat",
        chat_role=ChatRole.CLIENT_CHAT.value,
    )
    session.add(chat)
    await session.flush()
    proj = StudioProject(slug="b13-proj", name="B13 Project", description=None, status="active")
    session.add(proj)
    await session.flush()
    rule = StudioAssistantRule(
        scope=AssistantRuleScope.GLOBAL,
        project_id=None,
        chat_id=None,
        rule_text="hello rule b13",
        status=AssistantRuleStatus.ACTIVE,
        source=AssistantRuleSource.MANUAL,
    )
    session.add(rule)
    doc = StudioKnowledgeDocument(
        title="kb b13",
        source_type="manual",
        status=KnowledgeDocumentStatus.DRAFT,
        project_id=None,
    )
    session.add(doc)
    inc = StudioSlaIncident(
        chat_id=chat.id,
        chat_role=ChatRole.CLIENT_CHAT.value,
        trigger_message_id=None,
        status=SlaIncidentStatus.OPEN.value,
        severity=SlaSeverity.WARNING.value,
        due_at=now,
        detected_at=now,
    )
    session.add(inc)
    await session.commit()

    for path in (
        f"/admin/chats/{chat.id}",
        f"/admin/projects/{proj.id}",
        f"/admin/knowledge/documents/{doc.id}",
        f"/admin/sla/incidents/{inc.id}",
        f"/admin/assistant-rules/{rule.id}",
    ):
        r = await client.get(path, headers=_h())
        assert r.status_code == 200, path
        assert ADMIN_UI_TOKEN not in r.text, path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_post_requires_auth(b13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, _ = b13_client
    r = await client.post("/admin/projects", data={"slug": "x", "name": "Y"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/admin/login" in (r.headers.get("location") or "")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_project_via_form(b13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = b13_client
    r = await client.post(
        "/admin/projects",
        data={"slug": "from-admin-b13", "name": "From Admin", "description": ""},
        headers=_h(),
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    loc = r.headers.get("location") or ""
    assert "/admin/projects/" in loc
    row = await session.scalar(select(StudioProject).where(StudioProject.slug == "from-admin-b13"))
    assert row is not None
    assert row.name == "From Admin"
    assert ADMIN_UI_TOKEN not in loc
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_set_chat_role_via_form(b13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = b13_client
    chat = StudioChat(
        telegram_chat_id=-200111222,
        chat_type="supergroup",
        title="role test",
        chat_role=ChatRole.UNKNOWN.value,
    )
    session.add(chat)
    await session.commit()
    r = await client.post(
        f"/admin/chats/{chat.id}/role",
        data={"role": ChatRole.INTERNAL_CHAT.value},
        headers=_h(),
        follow_redirects=False,
    )
    assert r.status_code == 303
    await session.refresh(chat)
    assert chat.chat_role == ChatRole.INTERNAL_CHAT.value
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sla_ack_changes_status(b13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, session = b13_client
    now = datetime.now(timezone.utc)
    chat = StudioChat(telegram_chat_id=-300333444, chat_type="supergroup", title="sla", chat_role="client_chat")
    session.add(chat)
    await session.flush()
    inc = StudioSlaIncident(
        chat_id=chat.id,
        chat_role="client_chat",
        trigger_message_id=None,
        status=SlaIncidentStatus.OPEN.value,
        severity=SlaSeverity.WARNING.value,
        due_at=now,
        detected_at=now,
    )
    session.add(inc)
    await session.commit()
    r = await client.post(f"/admin/sla/incidents/{inc.id}/ack", headers=_h(), follow_redirects=False)
    assert r.status_code == 303
    await session.refresh(inc)
    assert inc.status == SlaIncidentStatus.ACKNOWLEDGED.value
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_detail_not_found(b13_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", ADMIN_UI_TOKEN)
    get_settings.cache_clear()
    client, _ = b13_client
    rid = uuid4()
    r = await client.get(f"/admin/chats/{rid}", headers=_h())
    assert r.status_code == 404
    get_settings.cache_clear()
