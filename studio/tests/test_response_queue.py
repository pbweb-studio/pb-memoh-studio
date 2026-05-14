from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pb_studio.response_queue.schemas import InboundEnqueue
from pb_studio.response_queue.service import QueueService
from pb_studio.response_queue.statuses import TurnStatus


def t0() -> datetime:
    return datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)


class AnsweringProcessor:
    async def finalize_turn(self, **kwargs) -> str:
        return TurnStatus.ANSWERED.value


class IgnoringProcessor:
    async def finalize_turn(self, **kwargs) -> str:
        return TurnStatus.IGNORED_BY_POLICY.value


class BadProcessor:
    async def finalize_turn(self, **kwargs) -> str:
        return "not_a_valid_status"


@pytest.mark.asyncio
async def test_dedupe_telegram_message_id(session_factory):
    svc = QueueService(2.0)
    now = t0()
    p = InboundEnqueue(telegram_chat_id=-100, body_text="a", telegram_message_id="m1")
    async with session_factory() as s:
        r1 = await svc.enqueue(s, p, now=now)
        await s.commit()
    async with session_factory() as s:
        r2 = await svc.enqueue(s, p, now=now)
        await s.commit()
    assert r1.duplicate is False
    assert r2.duplicate is True
    assert r1.dedupe_key == r2.dedupe_key
    assert r1.turn_id == r2.turn_id


@pytest.mark.asyncio
async def test_order_single_chat_merged_text(session_factory):
    svc = QueueService(2.0)
    now = t0()
    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=1, body_text="first", telegram_message_id="a"),
            now=now,
        )
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=1, body_text="second", telegram_message_id="b"),
            now=now + timedelta(seconds=1),
        )
        await s.commit()
    async with session_factory() as s:
        n = await svc.flush_due_turns(s, now=now + timedelta(seconds=3))
        await s.commit()
    assert n == 1
    async with session_factory() as s:
        out = await svc.dispatch_next(s, AnsweringProcessor(), now=now + timedelta(seconds=4))
        await s.commit()
    assert out is not None
    _tid, status, merged = out
    assert status == TurnStatus.ANSWERED.value
    assert merged == "first\n\nsecond"


@pytest.mark.asyncio
async def test_parallel_chats_independent(session_factory):
    """Два чата: оба debounced, dispatch дважды — разные merged_text (без гонки одного turn)."""
    svc = QueueService(2.0)
    base = t0()
    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=10, body_text="A", telegram_message_id="10-1"),
            now=base,
        )
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=20, body_text="B", telegram_message_id="20-1"),
            now=base,
        )
        await s.commit()
    async with session_factory() as s:
        await svc.flush_due_turns(s, now=base + timedelta(seconds=3))
        await s.commit()
    async with session_factory() as s:
        out1 = await svc.dispatch_next(s, AnsweringProcessor(), now=base + timedelta(seconds=4))
        out2 = await svc.dispatch_next(s, AnsweringProcessor(), now=base + timedelta(seconds=4))
        await s.commit()
    texts = {out1[2], out2[2]}
    assert texts == {"A", "B"}


@pytest.mark.asyncio
async def test_debounce_extends_window(session_factory):
    svc = QueueService(3.0)
    now = t0()
    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=5, body_text="x", telegram_message_id="1"),
            now=now,
        )
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=5, body_text="y", telegram_message_id="2"),
            now=now + timedelta(seconds=2),
        )
        await s.commit()
    async with session_factory() as s:
        assert await svc.flush_due_turns(s, now=now + timedelta(seconds=3)) == 0
        await s.commit()
    async with session_factory() as s:
        assert await svc.flush_due_turns(s, now=now + timedelta(seconds=5)) == 1
        await s.commit()


@pytest.mark.asyncio
async def test_no_inbound_rows_lost(session_factory):
    svc = QueueService(2.0)
    now = t0()
    async with session_factory() as s:
        for i in range(5):
            await svc.enqueue(
                s,
                InboundEnqueue(telegram_chat_id=99, body_text=f"L{i}", telegram_message_id=f"id{i}"),
                now=now + timedelta(milliseconds=100 * i),
            )
        await s.commit()
    async with session_factory() as s:
        await svc.flush_due_turns(s, now=now + timedelta(seconds=10))
        await s.commit()
    async with session_factory() as s:
        await svc.dispatch_next(s, AnsweringProcessor(), now=now + timedelta(seconds=11))
        await s.commit()
    from sqlalchemy import func, select

    from pb_studio.response_queue.models import InboundMessage

    async with session_factory() as s:
        cnt = await s.scalar(select(func.count()).select_from(InboundMessage))
    assert int(cnt) == 5


@pytest.mark.asyncio
async def test_final_statuses(session_factory):
    svc = QueueService(2.0)
    now = t0()
    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=7, body_text="z", telegram_message_id="z1"),
            now=now,
        )
        await s.commit()
    async with session_factory() as s:
        await svc.flush_due_turns(s, now=now + timedelta(seconds=3))
        await s.commit()
    async with session_factory() as s:
        out = await svc.dispatch_next(s, IgnoringProcessor(), now=now + timedelta(seconds=4))
        await s.commit()
    assert out and out[1] == TurnStatus.IGNORED_BY_POLICY.value


@pytest.mark.asyncio
async def test_processor_exception_marks_failed(session_factory):
    svc = QueueService(2.0)
    now = t0()

    class Boom:
        async def finalize_turn(self, **kwargs):
            raise RuntimeError("boom")

    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=8, body_text="e", telegram_message_id="e1"),
            now=now,
        )
        await s.commit()
    async with session_factory() as s:
        await svc.flush_due_turns(s, now=now + timedelta(seconds=3))
        await s.commit()
    async with session_factory() as s:
        out = await svc.dispatch_next(s, Boom(), now=now + timedelta(seconds=4))
        await s.commit()
    assert out is not None
    assert out[1] == TurnStatus.FAILED_WITH_ERROR.value


@pytest.mark.asyncio
async def test_bad_processor_status_raises(session_factory):
    svc = QueueService(2.0)
    now = t0()
    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=9, body_text="q", telegram_message_id="q1"),
            now=now,
        )
        await s.commit()
    async with session_factory() as s:
        await svc.flush_due_turns(s, now=now + timedelta(seconds=3))
        await s.commit()
    with pytest.raises(ValueError, match="non-terminal"):
        async with session_factory() as s:
            await svc.dispatch_next(s, BadProcessor(), now=now + timedelta(seconds=4))
            await s.commit()


@pytest.mark.asyncio
async def test_cancel_pending_turn(session_factory):
    svc = QueueService(2.0)
    now = t0()
    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=3, body_text="c", telegram_message_id="c1"),
            now=now,
        )
        ok = await svc.cancel_pending_turn(s, 3, now=now)
        await s.commit()
    assert ok is True
    async with session_factory() as s:
        assert await svc.flush_due_turns(s, now=now + timedelta(seconds=10)) == 0
        await s.commit()


@pytest.mark.asyncio
async def test_fifo_second_turn_after_first_answered(session_factory):
    svc = QueueService(2.0)
    now = t0()
    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=4, body_text="wave1", telegram_message_id="w1"),
            now=now,
        )
        await s.commit()
    async with session_factory() as s:
        await svc.flush_due_turns(s, now=now + timedelta(seconds=3))
        await s.commit()
    async with session_factory() as s:
        await svc.dispatch_next(s, AnsweringProcessor(), now=now + timedelta(seconds=4))
        await s.commit()
    async with session_factory() as s:
        await svc.enqueue(
            s,
            InboundEnqueue(telegram_chat_id=4, body_text="wave2", telegram_message_id="w2"),
            now=now + timedelta(seconds=10),
        )
        await s.commit()
    async with session_factory() as s:
        await svc.flush_due_turns(s, now=now + timedelta(seconds=13))
        await s.commit()
    async with session_factory() as s:
        out = await svc.dispatch_next(s, AnsweringProcessor(), now=now + timedelta(seconds=14))
        await s.commit()
    assert out and out[2] == "wave2"
