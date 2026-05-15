"""Регрессия NL UX: человекочитаемый inventory/report, learning после @mention, модель, изоляция clarify."""

from __future__ import annotations

import re
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.models import StudioControlGroup
from pb_studio.core.config import Settings, get_settings
from pb_studio.event_mirror.models import StudioChat
from pb_studio.nl.constants import LearningType, NlInteractionStatus
from pb_studio.nl.executor import format_nl_reply
from pb_studio.nl.models import StudioNlInteraction
from pb_studio.nl.processor import _process_one_nl, _try_handle_confirmation_reply
from pb_studio.nl.router_deterministic import route_deterministic
from pb_studio.nl.schemas import IntentEnum, NLRouterDecision, RouterModeEnum
from pb_studio.nl.triggers import normalize_nl_router_input
from pb_studio.response_queue.models import Base
from pb_studio.summaries.constants import SummaryStatus


@pytest_asyncio.fixture
async def nl_ux_engine():
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
async def nl_ux_session(nl_ux_engine):
    factory = async_sessionmaker(nl_ux_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        cg = StudioChat(
            telegram_chat_id=-99001,
            chat_type="supergroup",
            title="Управление",
            chat_role=ChatRole.CONTROL_GROUP.value,
        )
        session.add(cg)
        await session.flush()
        session.add(StudioControlGroup(chat_id=cg.id, is_active=True))
        session.add(
            StudioChat(
                telegram_chat_id=-99002,
                chat_type="supergroup",
                title="PBVOICE",
                chat_role=ChatRole.CLIENT_CHAT.value,
            )
        )
        session.add(
            StudioChat(
                telegram_chat_id=424242,
                chat_type="private",
                title="Денис",
                chat_role=ChatRole.UNKNOWN.value,
            )
        )
        await session.commit()
        yield session, cg.id


def test_normalize_then_learning_behavior_rule():
    s = Settings()
    raw = "@jarvispbweb_bot запомни: не смешивать ответы между разными вопросами"
    norm = normalize_nl_router_input(raw, s)
    d = route_deterministic(norm)
    assert d.mode == RouterModeEnum.learning
    assert d.intent == IntentEnum.learning_request
    assert d.parameters.get("learning_type") == LearningType.BEHAVIOR_RULE
    assert "не смешивать" in str(d.parameters.get("suggested_rule_text") or "").lower()


def test_runtime_model_query_not_clarify():
    d = route_deterministic("на какой модели ты работаешь?")
    assert d.mode == RouterModeEnum.business_action
    assert d.intent == IntentEnum.runtime_config_query


@pytest.mark.asyncio
async def test_format_nl_list_chats_human_no_uuid_tg_role(nl_ux_session):
    session, _cg_id = nl_ux_session
    settings = Settings()
    decision = NLRouterDecision(
        mode=RouterModeEnum.business_action,
        intent=IntentEnum.list_chats,
        confidence=0.9,
        parameters={},
    )
    out = await format_nl_reply(session, settings, decision, raw_input="какие чаты")
    assert "tg=" not in out
    assert "role=" not in out.lower()
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out, re.I)
    assert "группа PBVOICE" in out
    assert "личка с" in out and "Денис" in out


@pytest.mark.asyncio
async def test_format_nl_digest_human_no_summary_id_status(nl_ux_session, monkeypatch):
    session, _cg_id = nl_ux_session
    settings = Settings(studio_nl_digest_debug=False)

    class _FakeSummary:
        id = uuid.uuid4()
        status = SummaryStatus.GENERATED
        summary_text = "Команда закрыла задачу по интеграции."

    async def _fake_ensure(*_a, **_k):
        return _FakeSummary()

    with patch("pb_studio.nl.executor.ensure_chat_summary_for_period", new_callable=AsyncMock) as m:
        m.side_effect = _fake_ensure
        decision = NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.studio_digest,
            confidence=0.9,
            parameters={"period": "today"},
        )
        out = await format_nl_reply(session, settings, decision, raw_input="отчёт за сегодня")

    assert "summary_id" not in out
    assert "status=" not in out
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out, re.I)
    assert "интеграции" in out


@pytest.mark.asyncio
async def test_try_handle_confirmation_skips_independent_question(nl_ux_session):
    session, cg_id = nl_ux_session
    settings = Settings(studio_nl_commands_enabled=True)

    pending = StudioNlInteraction(
        source_message_id=100,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=777,
        input_text="запомни: старое правило",
        normalized_text="",
        trigger_type="mention",
        mode="learning",
        status=NlInteractionStatus.PENDING_CONFIRMATION,
        parameters_json={},
        decision_json={
            "pending_learning": {
                "learning_type": LearningType.BEHAVIOR_RULE,
                "suggested_rule_text": "старое правило",
            }
        },
    )
    session.add(pending)
    await session.flush()

    row = StudioNlInteraction(
        source_message_id=101,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=777,
        input_text="на какой модели ты работаешь?",
        normalized_text="",
        trigger_type="mention",
        mode="router_pending",
        status=NlInteractionStatus.PENDING,
        parameters_json={},
        decision_json={},
    )
    session.add(row)
    await session.commit()

    handled = await _try_handle_confirmation_reply(session, settings, row, send_message=None)
    assert handled is False
    await session.refresh(pending)
    assert pending.status == NlInteractionStatus.PENDING_CONFIRMATION


@pytest.mark.asyncio
async def test_process_one_nl_single_outbound_send(nl_ux_session, monkeypatch):
    session, cg_id = nl_ux_session
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_NL_ROUTER_PROVIDER", "deterministic")
    get_settings.cache_clear()
    settings = get_settings()

    sends: list[str] = []

    async def _capture_send(_sess, _set, text, send_message=None):
        sends.append(text)
        return True, None, len(sends)

    row = StudioNlInteraction(
        source_message_id=200,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=888,
        input_text="какие чаты ты видишь",
        normalized_text="",
        trigger_type="mention",
        mode="router_pending",
        status=NlInteractionStatus.PENDING,
        parameters_json={},
        decision_json={},
    )
    session.add(row)
    await session.commit()

    with patch("pb_studio.nl.processor._send_text_to_control_group", new_callable=AsyncMock) as m:
        m.side_effect = _capture_send
        await _process_one_nl(session, row, settings, send_message=None)
        await session.commit()

    assert len(sends) == 1
    assert "группа PBVOICE" in sends[0]
    await session.refresh(row)
    assert row.status == NlInteractionStatus.PROCESSED


@pytest.mark.asyncio
async def test_runtime_config_display_name_from_settings(nl_ux_session):
    session, _ = nl_ux_session
    settings = Settings(studio_memoh_model_display_name="gpt-4.1-mini (prod)")
    decision = NLRouterDecision(
        mode=RouterModeEnum.business_action,
        intent=IntentEnum.runtime_config_query,
        confidence=0.91,
        parameters={},
    )
    out = await format_nl_reply(session, settings, decision, raw_input="модель?")
    assert "gpt-4.1-mini" in out
