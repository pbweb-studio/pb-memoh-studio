"""Фаза 11a: assistant rules — storage, API, control commands (без LLM)."""

from __future__ import annotations

from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pb_studio.assistant_rules.models  # noqa: F401
import pb_studio.control_commands.models  # noqa: F401
import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.knowledge.models  # noqa: F401
import pb_studio.project_digests.models  # noqa: F401
import pb_studio.projects.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.assistant_rules.constants import AssistantRuleStatus
from pb_studio.assistant_rules.models import StudioAssistantRule
from pb_studio.control_commands.constants import ControlCommandName, ControlCommandStatus
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.event_mirror.models import StudioChat
from pb_studio.control_commands.parser import parse_control_group_command_line
from pb_studio.control_commands.service import run_control_commands_cycle
from pb_studio.core.config import get_settings
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def ar_engine():
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
async def ar_client(ar_engine):
    factory = async_sessionmaker(ar_engine, class_=AsyncSession, expire_on_commit=False)
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


def _env11a(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm11a")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_api_create_list_get_patch_disable_audit(ar_client, monkeypatch):
    _env11a(monkeypatch)
    client, session = ar_client
    h = {"Authorization": "Bearer adm11a"}
    r = await client.post(
        "/assistant-rules",
        headers=h,
        json={"scope": "global", "rule_text": "Be polite.", "source": "manual"},
    )
    assert r.status_code == 201
    rid = r.json()["id"]
    lst = await client.get("/assistant-rules", headers=h)
    assert lst.status_code == 200
    assert len(lst.json()) >= 1
    one = await client.get(f"/assistant-rules/{rid}", headers=h)
    assert one.status_code == 200
    assert one.json()["rule_text"] == "Be polite."
    p = await client.patch(f"/assistant-rules/{rid}", headers=h, json={"rule_text": "Be concise."})
    assert p.status_code == 200
    assert p.json()["rule_text"] == "Be concise."
    d = await client.post(f"/assistant-rules/{rid}/disable", headers=h, json={"reason": "test off"})
    assert d.status_code == 200
    assert d.json()["status"] == AssistantRuleStatus.DISABLED
    aud = await client.get("/assistant-rules/audit", headers=h)
    assert aud.status_code == 200
    assert len(aud.json()) >= 2
    aud_f = await client.get("/assistant-rules/audit", headers=h, params={"rule_id": rid})
    assert len(aud_f.json()) >= 1
    for a in aud_f.json():
        assert a["rule_id"] == rid or a["rule_id"] == str(rid)


@pytest.mark.asyncio
async def test_api_project_and_chat_scope(ar_client, monkeypatch):
    _env11a(monkeypatch)
    client, session = ar_client
    h = {"Authorization": "Bearer adm11a"}
    pr = await client.post("/projects", headers=h, json={"slug": "r11", "name": "R11"})
    pid = pr.json()["id"]
    await client.post("/events/telegram", json=_msg(501001, -50101, text="x", message_id=1))
    cg = (await session.execute(select(StudioChat).where(StudioChat.telegram_chat_id == -50101))).scalar_one()
    r1 = await client.post(
        "/assistant-rules",
        headers=h,
        json={"scope": "project", "project_id": pid, "rule_text": "proj rule", "source": "manual"},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/assistant-rules",
        headers=h,
        json={"scope": "chat", "chat_id": str(cg.id), "rule_text": "chat rule", "source": "manual"},
    )
    assert r2.status_code == 201


@pytest.mark.asyncio
async def test_api_requires_admin(ar_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "sec11a")
    get_settings.cache_clear()
    client, _session = ar_client
    r = await client.get("/assistant-rules")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rule_commands_control_group(ar_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm11a")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK11A")
    get_settings.cache_clear()
    client, session = ar_client
    h = {"Authorization": "Bearer adm11a"}
    await client.post("/projects", headers=h, json={"slug": "rcg", "name": "RCG"})
    await client.post("/events/telegram", json=_msg(502001, -50201, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -50201})
    await client.post("/events/telegram", json=_msg(502002, -50201, text="/rule_add Always use UTC", message_id=2))
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd is not None
    assert cmd.command_name == ControlCommandName.RULE_ADD
    assert cmd.status == ControlCommandStatus.PROCESSED
    n = await session.scalar(select(func.count()).select_from(StudioAssistantRule))
    assert int(n or 0) >= 1


@pytest.mark.asyncio
async def test_rule_acl_denied(ar_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm11a")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK11A")
    get_settings.cache_clear()
    client, session = ar_client
    h = {"Authorization": "Bearer adm11a"}
    await client.post("/events/telegram", json=_msg(503001, -50301, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -50301})
    await client.post(
        "/events/telegram",
        json=_msg(503002, -50301, text="/rule_add x", message_id=2, from_user_id=99),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED
    n = await session.scalar(select(func.count()).select_from(StudioAssistantRule))
    assert int(n or 0) == 0


@pytest.mark.asyncio
async def test_rule_list_outside_control_group_not_scanned(ar_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm11a")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    get_settings.cache_clear()
    client, session = ar_client
    h = {"Authorization": "Bearer adm11a"}
    await client.post("/events/telegram", json=_msg(504001, -50401, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -50401})
    await client.post("/events/telegram", json=_msg(504002, -50402, text="/rule_list", message_id=2))
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    n = await session.scalar(select(func.count()).select_from(StudioControlCommand))
    assert int(n or 0) == 0


def test_summary_kb_parse_regression():
    assert parse_control_group_command_line("/summary_help") is not None
    assert parse_control_group_command_line("/kb_list") is not None
    assert parse_control_group_command_line("/project_list") is not None
    r = parse_control_group_command_line("/rule_disable 00000000-0000-4000-8000-000000000001")
    assert r is not None
    assert r.name == ControlCommandName.RULE_DISABLE
