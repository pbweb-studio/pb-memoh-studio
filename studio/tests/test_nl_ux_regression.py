"""Регрессия NL UX: человекочитаемый inventory/report, learning после @mention, модель, изоляция clarify."""

from __future__ import annotations

import re
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.models import StudioControlGroup
from pb_studio.core.config import Settings, get_settings
from pb_studio.event_mirror.models import StudioChat
from pb_studio.nl.constants import LearningType, NlInteractionStatus
from pb_studio.nl.executor import format_nl_reply
from pb_studio.nl.models import StudioNlInteraction
from pb_studio.nl.processor import _process_one_nl, _try_handle_confirmation_reply, run_nl_interactions_standalone
from pb_studio.nl.turn_input import nl_turn_router_input
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


def test_normalize_strips_mention_nbsp_before_zapomni():
    s = Settings()
    raw = "@jarvispbweb_bot\u00a0запомни: правило один"
    norm = normalize_nl_router_input(raw, s)
    assert norm.lower().startswith("запомни")
    d = route_deterministic(norm)
    assert d.mode == RouterModeEnum.learning


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
    assert "Вижу такие чаты" in out
    assert "•" in out
    assert "группа Управление" in out
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
async def test_format_nl_digest_sanitizes_debug_lines_in_summary_text(nl_ux_session, monkeypatch):
    session, _cg_id = nl_ux_session
    settings = Settings(studio_nl_digest_debug=False)

    class _FakeSummary:
        id = uuid.uuid4()
        status = SummaryStatus.GENERATED
        summary_text = "summary_id=deadbeef status=generated\nОбсудили релиз."

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
    assert "Обсудили релиз" in out


def test_sanitize_nl_summary_snippet_strips_debug_tokens():
    from pb_studio.nl.executor import _sanitize_nl_summary_snippet

    dirty = "summary_id=abc-abc-abc-abc-abcdefabcdef status=generated\nНормальный текст про задачу."
    clean = _sanitize_nl_summary_snippet(dirty)
    assert "summary_id" not in clean
    assert "Нормальный текст" in clean


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

    ti = nl_turn_router_input(row.input_text, settings)
    handled = await _try_handle_confirmation_reply(session, settings, row, turn_input=ti, send_message=None)
    assert handled is False
    await session.refresh(pending)
    assert pending.status == NlInteractionStatus.IGNORED
    assert pending.last_error == "superseded_by_new_turn"


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
async def test_process_one_nl_learning_row_with_leading_mention_nbsp(nl_ux_session, monkeypatch):
    session, cg_id = nl_ux_session
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_NL_ROUTER_PROVIDER", "deterministic")
    get_settings.cache_clear()
    settings = get_settings()

    sends: list[str] = []

    async def _capture_send(_sess, _set, text, send_message=None):
        sends.append(text)
        return True, None, 1

    row = StudioNlInteraction(
        source_message_id=501,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=888,
        input_text="@jarvispbweb_bot\u00a0запомни: не смешивать ответы",
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
    assert "Понял как правило" in sends[0]
    await session.refresh(row)
    assert row.status == NlInteractionStatus.PENDING_CONFIRMATION


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


@pytest.mark.asyncio
async def test_runtime_config_empty_uses_memoh_admin_hint(nl_ux_session):
    session, _ = nl_ux_session
    settings = Settings(studio_memoh_model_display_name="")
    decision = NLRouterDecision(
        mode=RouterModeEnum.business_action,
        intent=IntentEnum.runtime_config_query,
        confidence=0.91,
        parameters={},
    )
    out = await format_nl_reply(session, settings, decision, raw_input="модель?")
    assert "Memoh Admin" in out
    assert "не могу надёжно" in out.lower()


@pytest.mark.asyncio
async def test_off_by_one_three_sequential_nl_replies(nl_ux_session, monkeypatch):
    """A: три разных вопроса — три разных ответа без переноса inventory/digest в «модель»."""
    session, cg_id = nl_ux_session
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_NL_ROUTER_PROVIDER", "deterministic")
    get_settings.cache_clear()
    settings = Settings(studio_memoh_model_display_name="pytest-model-xyz")

    class _FakeSummary:
        id = uuid.uuid4()
        status = SummaryStatus.GENERATED
        summary_text = "Секция отчёта за сегодня: закрыли задачу отчётной линии."

    async def _fake_ensure(*_a, **_k):
        return _FakeSummary()

    sends: list[str] = []

    async def _capture_send(_sess, _set, text, send_message=None):
        sends.append(text)
        return True, None, len(sends)

    mids = (401, 402, 403)
    texts = (
        "какие чаты ты видишь?",
        "дай отчёт за сегодня",
        "на какой модели ты работаешь?",
    )
    for mid, txt in zip(mids, texts, strict=True):
        session.add(
            StudioNlInteraction(
                source_message_id=mid,
                control_group_chat_id=cg_id,
                sender_telegram_user_id=902,
                input_text=txt,
                normalized_text="",
                trigger_type="mention",
                mode="router_pending",
                status=NlInteractionStatus.PENDING,
                parameters_json={},
                decision_json={},
            )
        )
    await session.commit()

    with (
        patch("pb_studio.nl.processor._send_text_to_control_group", new_callable=AsyncMock) as _m_send,
        patch("pb_studio.nl.executor.ensure_chat_summary_for_period", new_callable=AsyncMock) as m_sum,
    ):
        _m_send.side_effect = _capture_send
        m_sum.side_effect = _fake_ensure
        for mid in mids:
            row = (
                await session.scalars(
                    select(StudioNlInteraction).where(StudioNlInteraction.source_message_id == mid)
                )
            ).first()
            assert row is not None
            await _process_one_nl(session, row, settings, send_message=None)
            await session.commit()

    assert len(sends) == 3
    out1, out2, out3 = sends
    assert "PBVOICE" in out1 or "Управление" in out1
    assert "отчётной линии" in out2 or "закрыли задачу" in out2
    assert "pytest-model-xyz" in out3
    assert "PBVOICE" not in out3
    assert "отчётной линии" not in out3


@pytest.mark.asyncio
async def test_run_nl_interactions_fifo_two_pending(nl_ux_session, nl_ux_engine, monkeypatch):
    """C: run_nl обрабатывает две PENDING-строки подряд (по одной транзакции)."""
    _session, cg_id = nl_ux_session
    factory = async_sessionmaker(nl_ux_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    import pb_studio.core.database as db

    async def _dispose_clear_globals() -> None:
        db._engine = None
        db._session_factory = None

    monkeypatch.setattr("pb_studio.nl.processor.dispose_engine", _dispose_clear_globals)
    monkeypatch.setattr("pb_studio.nl.processor.get_session_factory", lambda settings=None: factory)

    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_NL_ROUTER_PROVIDER", "deterministic")
    get_settings.cache_clear()
    settings = get_settings()

    async with factory() as s:
        for mid in (601, 602):
            s.add(
                StudioNlInteraction(
                    source_message_id=mid,
                    control_group_chat_id=cg_id,
                    sender_telegram_user_id=903,
                    input_text="какие чаты" if mid == 601 else "модель?",
                    normalized_text="",
                    trigger_type="mention",
                    mode="router_pending",
                    status=NlInteractionStatus.PENDING,
                    parameters_json={},
                    decision_json={},
                )
            )
        await s.commit()

    with patch("pb_studio.nl.processor._send_text_to_control_group", new_callable=AsyncMock) as m:
        m.return_value = (True, None, 1)
        counts = await run_nl_interactions_standalone(settings=settings, batch_limit=10)
    assert counts["processed_nl"] == 2
    assert m.await_count == 2


@pytest.mark.asyncio
async def test_process_one_nl_skips_non_pending_row(nl_ux_session, monkeypatch, caplog):
    session, cg_id = nl_ux_session
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_NL_ROUTER_PROVIDER", "deterministic")
    get_settings.cache_clear()
    settings = get_settings()

    row = StudioNlInteraction(
        source_message_id=700,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=904,
        input_text="какие чаты",
        normalized_text="",
        trigger_type="mention",
        mode="router_pending",
        status=NlInteractionStatus.PROCESSED,
        parameters_json={},
        decision_json={},
        reply_text="already",
    )
    session.add(row)
    await session.commit()

    import logging

    caplog.set_level(logging.WARNING)
    with patch("pb_studio.nl.processor._send_text_to_control_group", new_callable=AsyncMock) as m:
        await _process_one_nl(session, row, settings, send_message=None)
        await session.commit()
    m.assert_not_awaited()
    assert "nl_process_skip_non_pending" in caplog.text
