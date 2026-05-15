"""Unit tests for MVP v1 MCP handlers (pb_studio.mcp_tools.extra_handlers)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pb_studio.assistant_rules.constants import AssistantRuleScope, AssistantRuleStatus
from pb_studio.assistant_rules.models import StudioAssistantRule
from pb_studio.control_group.constants import ChatRole
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.mcp_tools import extra_handlers as h
from pb_studio.projects.models import StudioProject, StudioProjectChat


@pytest_asyncio.fixture
async def studio_session(session_factory, monkeypatch: pytest.MonkeyPatch):
    """Patch handler's session factory to point at in-memory test DB; yield a session for seeding."""

    monkeypatch.setattr(
        "pb_studio.mcp_tools.extra_handlers.get_session_factory",
        lambda settings=None: session_factory,
    )
    async with session_factory() as session:
        yield session


async def _seed_chat(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    title: str = "Test chat",
    chat_role: str = ChatRole.UNKNOWN.value,
) -> StudioChat:
    chat = StudioChat(
        telegram_chat_id=telegram_chat_id,
        chat_type="supergroup",
        title=title,
        chat_role=chat_role,
    )
    session.add(chat)
    await session.flush()
    await session.commit()
    return chat


async def _seed_messages(
    session: AsyncSession,
    *,
    chat: StudioChat,
    texts: list[str],
    base_time: datetime | None = None,
) -> None:
    base = base_time or datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    for idx, text in enumerate(texts):
        session.add(
            StudioMessage(
                chat_id=chat.id,
                telegram_message_id=1000 + idx,
                date=base + timedelta(minutes=idx),
                text=text,
                caption=None,
                raw_message={"text": text},
            )
        )
    await session.commit()


# ===== studio_get_chat_context =====


@pytest.mark.asyncio
async def test_chat_context_unknown_chat(studio_session: AsyncSession) -> None:
    out = await h.studio_get_chat_context(telegram_chat_id=-999999, from_user_id=1)
    assert "chat_unknown=true" in out


@pytest.mark.asyncio
async def test_chat_context_internal_chat_can_respond(studio_session: AsyncSession) -> None:
    await _seed_chat(studio_session, telegram_chat_id=-1001, chat_role=ChatRole.INTERNAL_CHAT.value)
    out = await h.studio_get_chat_context(telegram_chat_id=-1001, from_user_id=42)
    assert "role=internal_chat" in out
    assert "can_respond_to_user=yes" in out
    assert "project=none" in out


@pytest.mark.asyncio
async def test_chat_context_client_chat_blocks_unknown_user(
    studio_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", "555,666")
    from pb_studio.core.config import get_settings

    get_settings.cache_clear()
    await _seed_chat(studio_session, telegram_chat_id=-1002, chat_role=ChatRole.CLIENT_CHAT.value)
    out_blocked = await h.studio_get_chat_context(telegram_chat_id=-1002, from_user_id=123)
    assert "can_respond_to_user=no" in out_blocked
    assert "client_chat" in out_blocked
    out_allowed = await h.studio_get_chat_context(telegram_chat_id=-1002, from_user_id=555)
    assert "can_respond_to_user=yes" in out_allowed


@pytest.mark.asyncio
async def test_chat_context_includes_active_rules(studio_session: AsyncSession) -> None:
    await _seed_chat(studio_session, telegram_chat_id=-1003, chat_role=ChatRole.INTERNAL_CHAT.value)
    studio_session.add(
        StudioAssistantRule(
            scope=AssistantRuleScope.GLOBAL,
            rule_text="Не отвечай на провокации.",
            status=AssistantRuleStatus.ACTIVE,
            source="manual",
        )
    )
    await studio_session.commit()
    out = await h.studio_get_chat_context(telegram_chat_id=-1003, from_user_id=42)
    assert "active_rules" in out
    assert "Не отвечай на провокации" in out


# ===== studio_assign_chat_role =====


@pytest.mark.asyncio
async def test_assign_chat_role_success(studio_session: AsyncSession) -> None:
    await _seed_chat(studio_session, telegram_chat_id=-2001)
    out = await h.studio_assign_chat_role(telegram_chat_id=-2001, role="project_chat")
    assert "project_chat" in out


@pytest.mark.asyncio
async def test_assign_chat_role_invalid(studio_session: AsyncSession) -> None:
    await _seed_chat(studio_session, telegram_chat_id=-2002)
    out = await h.studio_assign_chat_role(telegram_chat_id=-2002, role="wrong_role")
    assert "Недопустимая роль" in out


@pytest.mark.asyncio
async def test_assign_chat_role_control_group_blocked(studio_session: AsyncSession) -> None:
    await _seed_chat(studio_session, telegram_chat_id=-2003)
    out = await h.studio_assign_chat_role(telegram_chat_id=-2003, role="control_group")
    assert "studio_set_control_group" in out


@pytest.mark.asyncio
async def test_assign_chat_role_unknown_chat(studio_session: AsyncSession) -> None:
    out = await h.studio_assign_chat_role(telegram_chat_id=-99999, role="project_chat")
    assert "не виден Studio" in out


# ===== studio_set_control_group =====


@pytest.mark.asyncio
async def test_set_control_group_success(studio_session: AsyncSession) -> None:
    await _seed_chat(studio_session, telegram_chat_id=-3001, title="HQ")
    out = await h.studio_set_control_group(telegram_chat_id=-3001)
    assert "Управляющая группа установлена" in out
    assert "HQ" in out


# ===== studio_create_project + slug autogen =====


def test_autogen_slug_basic() -> None:
    assert h._autogen_slug("My Project Alpha") == "my-project-alpha"


def test_autogen_slug_cyrillic() -> None:
    assert h._autogen_slug("Проект Альфа") == "proekt-alfa"


@pytest.mark.asyncio
async def test_create_project_with_autogen_slug(studio_session: AsyncSession) -> None:
    out = await h.studio_create_project(name="Demo Project")
    assert "demo-project" in out
    assert "Проект создан" in out


# ===== studio_bind_chat_to_project =====


@pytest.mark.asyncio
async def test_bind_chat_to_project_promotes_role(studio_session: AsyncSession) -> None:
    chat = await _seed_chat(studio_session, telegram_chat_id=-4001, chat_role=ChatRole.UNKNOWN.value)
    await h.studio_create_project(name="Site Redesign", slug="site")
    out = await h.studio_bind_chat_to_project(
        telegram_chat_id=-4001, project_slug="site", role_in_project="primary"
    )
    assert "привязан к проекту" in out

    await studio_session.refresh(chat)
    assert chat.chat_role == ChatRole.PROJECT_CHAT.value


@pytest.mark.asyncio
async def test_bind_chat_to_project_missing_project(studio_session: AsyncSession) -> None:
    await _seed_chat(studio_session, telegram_chat_id=-4002)
    out = await h.studio_bind_chat_to_project(
        telegram_chat_id=-4002, project_slug="nonexistent", role_in_project="primary"
    )
    assert "не найден" in out


# ===== studio_get_active_rules =====


@pytest.mark.asyncio
async def test_get_active_rules_global(studio_session: AsyncSession) -> None:
    studio_session.add(
        StudioAssistantRule(
            scope=AssistantRuleScope.GLOBAL,
            rule_text="Будь вежлив.",
            status=AssistantRuleStatus.ACTIVE,
            source="manual",
        )
    )
    await studio_session.commit()
    out = await h.studio_get_active_rules(scope="global")
    assert "Будь вежлив" in out


@pytest.mark.asyncio
async def test_get_active_rules_invalid_scope(studio_session: AsyncSession) -> None:
    out = await h.studio_get_active_rules(scope="weird")
    assert "global | project | chat" in out


# ===== studio_disable_rule =====


@pytest.mark.asyncio
async def test_disable_rule_success(studio_session: AsyncSession) -> None:
    rule = StudioAssistantRule(
        scope=AssistantRuleScope.GLOBAL,
        rule_text="Тест.",
        status=AssistantRuleStatus.ACTIVE,
        source="manual",
    )
    studio_session.add(rule)
    await studio_session.commit()
    rid = str(rule.id)
    out = await h.studio_disable_rule(rule_id=rid)
    assert "отключено" in out


@pytest.mark.asyncio
async def test_disable_rule_invalid_uuid(studio_session: AsyncSession) -> None:
    out = await h.studio_disable_rule(rule_id="not-a-uuid")
    assert "UUID" in out


# ===== studio_get_recent_messages =====


@pytest.mark.asyncio
async def test_get_recent_messages_by_telegram_id(studio_session: AsyncSession) -> None:
    chat = await _seed_chat(studio_session, telegram_chat_id=-5001, title="Sales Chat")
    await _seed_messages(studio_session, chat=chat, texts=["задача 1", "задача 2"])
    out = await h.studio_get_recent_messages(chat_id_or_name="-5001", limit=10)
    assert "задача 1" in out
    assert "задача 2" in out


@pytest.mark.asyncio
async def test_get_recent_messages_by_title_substring(studio_session: AsyncSession) -> None:
    chat = await _seed_chat(studio_session, telegram_chat_id=-5002, title="Project Alpha team")
    await _seed_messages(studio_session, chat=chat, texts=["встретимся в 14:00"])
    out = await h.studio_get_recent_messages(chat_id_or_name="alpha", limit=10)
    assert "встретимся в 14:00" in out


# ===== studio_smart_chat_report (LLM fallback) =====


@pytest.mark.asyncio
async def test_smart_chat_report_without_llm_settings(
    studio_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STUDIO_KB_CHAT_API_BASE_URL", raising=False)
    monkeypatch.delenv("STUDIO_KB_CHAT_API_KEY", raising=False)
    from pb_studio.core.config import get_settings

    get_settings.cache_clear()
    chat = await _seed_chat(studio_session, telegram_chat_id=-6001, title="LLM-less chat")
    await _seed_messages(studio_session, chat=chat, texts=["hello", "world"])
    out = await h.studio_smart_chat_report(chat_id_or_name="-6001", period="today")
    assert "LLM-отчёт недоступен" in out
    assert "2" in out


@pytest.mark.asyncio
async def test_smart_chat_report_no_messages(studio_session: AsyncSession) -> None:
    await _seed_chat(studio_session, telegram_chat_id=-6002, title="Quiet chat")
    out = await h.studio_smart_chat_report(chat_id_or_name="-6002", period="today")
    assert "сообщений не было" in out
