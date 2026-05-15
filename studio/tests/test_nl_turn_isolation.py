"""Изоляция NL-turn: очистка цитат, роутинг без хвостов, pending learning."""

from __future__ import annotations

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
from pb_studio.nl.models import StudioNlInteraction
from pb_studio.nl.processor import _process_one_nl, _try_handle_confirmation_reply
from pb_studio.nl.router import route_nl
from pb_studio.nl.schemas import IntentEnum, NLRouterDecision, RouterModeEnum
from pb_studio.nl.turn_input import nl_turn_router_input, strip_reply_decorations
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def iso_engine():
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
async def iso_session(iso_engine):
    factory = async_sessionmaker(iso_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        cg = StudioChat(
            telegram_chat_id=-77001,
            chat_type="supergroup",
            title="CG",
            chat_role=ChatRole.CONTROL_GROUP.value,
        )
        session.add(cg)
        await session.flush()
        session.add(StudioControlGroup(chat_id=cg.id, is_active=True))
        await session.commit()
        yield session, cg.id


def test_strip_reply_decorations_blockquote_and_bracket():
    raw = "> старый ответ бота\n> вторая строка\nна какой модели ты работаешь?"
    assert strip_reply_decorations(raw) == "на какой модели ты работаешь?"
    raw2 = "[Reply to Bot: что-то]\nдай отчёт за сегодня"
    assert strip_reply_decorations(raw2) == "дай отчёт за сегодня"


@pytest.mark.asyncio
async def test_nl_turn_inventory_tail_then_model_no_inventory_marker():
    settings = Settings()
    poison = (
        "> Чаты Studio (кроме активной control group):\n"
        "> — группа PBVOICE\n"
        "на какой модели ты работаешь?"
    )
    turn = nl_turn_router_input(poison, settings)
    assert "PBVOICE" not in turn
    assert "Чаты Studio" not in turn
    d = await route_nl(settings, turn)
    assert d.intent == IntentEnum.runtime_config_query


@pytest.mark.asyncio
async def test_nl_turn_inventory_tail_then_digest():
    settings = Settings()
    poison = (
        "> — группа X\n"
        "> — группа Y\n"
        "дай отчёт за сегодня"
    )
    turn = nl_turn_router_input(poison, settings)
    assert "группа X" not in turn
    d = await route_nl(settings, turn)
    assert d.intent == IntentEnum.studio_digest


@pytest.mark.asyncio
async def test_learning_pending_model_supersedes_pending(iso_session):
    session, cg_id = iso_session
    settings = Settings(studio_nl_commands_enabled=True)

    pending = StudioNlInteraction(
        source_message_id=1,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=99,
        input_text="запомни: foo",
        normalized_text="",
        trigger_type="mention",
        mode="learning",
        status=NlInteractionStatus.PENDING_CONFIRMATION,
        parameters_json={},
        decision_json={
            "pending_learning": {
                "learning_type": LearningType.BEHAVIOR_RULE,
                "suggested_rule_text": "foo",
            }
        },
    )
    session.add(pending)
    await session.flush()

    row = StudioNlInteraction(
        source_message_id=2,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=99,
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
async def test_two_independent_route_calls_not_concatenated(iso_session, monkeypatch):
    session, cg_id = iso_session
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("STUDIO_NL_ROUTER_PROVIDER", "deterministic")
    get_settings.cache_clear()
    settings = get_settings()

    calls: list[str] = []

    async def _capture_route(_s, text: str):
        calls.append(text)
        if "чат" in text.lower():
            return NLRouterDecision(
                mode=RouterModeEnum.business_action,
                intent=IntentEnum.list_chats,
                confidence=0.9,
                parameters={},
            )
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.runtime_config_query,
            confidence=0.91,
            parameters={},
        )

    sends: list[str] = []

    async def _cap_send(_sess, _set, txt, send_message=None):
        sends.append(txt)
        return True, None, len(sends)

    with patch("pb_studio.nl.processor.route_nl", new_callable=AsyncMock) as m_route:
        m_route.side_effect = _capture_route
        with patch("pb_studio.nl.processor._send_text_to_control_group", new_callable=AsyncMock) as m_send:
            m_send.side_effect = _cap_send
            for mid, text in ((10, "какие чаты"), (11, "на какой модели ты?")):
                row = StudioNlInteraction(
                    source_message_id=mid,
                    control_group_chat_id=cg_id,
                    sender_telegram_user_id=42,
                    input_text=text,
                    normalized_text="",
                    trigger_type="mention",
                    mode="router_pending",
                    status=NlInteractionStatus.PENDING,
                    parameters_json={},
                    decision_json={},
                )
                session.add(row)
            await session.commit()
            rows = list(
                (
                    await session.scalars(
                        select(StudioNlInteraction).where(StudioNlInteraction.source_message_id.in_((10, 11)))
                    )
                ).all()
            )
            rows.sort(key=lambda r: int(r.source_message_id or 0))
            for row in rows:
                await _process_one_nl(session, row, settings, send_message=None)

    assert calls == ["какие чаты", "на какой модели ты?"]
    assert len(sends) == 2


@pytest.mark.asyncio
async def test_ambiguous_long_not_learning_confirmation(iso_session):
    session, cg_id = iso_session
    settings = Settings(studio_nl_commands_enabled=True)
    pending = StudioNlInteraction(
        source_message_id=50,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=5,
        input_text="запомни: x",
        normalized_text="",
        trigger_type="mention",
        mode="learning",
        status=NlInteractionStatus.PENDING_CONFIRMATION,
        parameters_json={},
        decision_json={
            "pending_learning": {"learning_type": LearningType.BEHAVIOR_RULE, "suggested_rule_text": "x"}
        },
    )
    session.add(pending)
    await session.flush()
    row = StudioNlInteraction(
        source_message_id=51,
        control_group_chat_id=cg_id,
        sender_telegram_user_id=5,
        input_text="это длинное сообщение не похоже ни на да ни на нет и явно не подтверждение",
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
    h = await _try_handle_confirmation_reply(session, settings, row, turn_input=ti, send_message=None)
    assert h is False
    await session.refresh(pending)
    assert pending.status == NlInteractionStatus.PENDING_CONFIRMATION
