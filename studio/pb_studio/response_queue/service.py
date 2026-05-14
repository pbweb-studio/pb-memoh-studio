from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pb_studio.response_queue.models import Base, InboundMessage, ResponseTurn
from pb_studio.response_queue.schemas import EnqueueResult, InboundEnqueue, TurnProcessor
from pb_studio.response_queue.statuses import TurnStatus

TERMINAL = frozenset(
    {
        TurnStatus.ANSWERED.value,
        TurnStatus.IGNORED_BY_POLICY.value,
        TurnStatus.FAILED_WITH_ERROR.value,
        TurnStatus.CANCELLED_BY_NEWER_REQUEST.value,
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_dedupe_key(chat_id: int, payload: InboundEnqueue) -> str:
    if payload.telegram_message_id:
        return f"c{chat_id}:m{payload.telegram_message_id}"
    if payload.idempotency_key:
        return f"c{chat_id}:i{payload.idempotency_key}"
    raise ValueError("telegram_message_id or idempotency_key is required for deduplication")


class QueueService:
    """Per-chat sequential turns, debounce, dedupe — Studio DB only (no Memoh)."""

    def __init__(self, debounce_seconds: float = 2.5) -> None:
        if debounce_seconds < 2.0 or debounce_seconds > 4.0:
            raise ValueError("debounce_seconds must be between 2 and 4 inclusive")
        self.debounce_seconds = float(debounce_seconds)
        self._locks_guard = asyncio.Lock()
        self._chat_locks: dict[int, asyncio.Lock] = {}

    async def _chat_lock(self, chat_id: int) -> asyncio.Lock:
        async with self._locks_guard:
            if chat_id not in self._chat_locks:
                self._chat_locks[chat_id] = asyncio.Lock()
            return self._chat_locks[chat_id]

    async def enqueue(self, session: AsyncSession, payload: InboundEnqueue, *, now: datetime | None = None) -> EnqueueResult:
        now = now or _utcnow()
        chat_id = payload.telegram_chat_id
        dedupe = build_dedupe_key(chat_id, payload)

        existing_inbound = await session.scalar(select(InboundMessage).where(InboundMessage.dedupe_key == dedupe))
        if existing_inbound is not None:
            return EnqueueResult(
                turn_id=existing_inbound.turn_id,
                inbound_id=existing_inbound.id,
                dedupe_key=dedupe,
                duplicate=True,
            )

        async with await self._chat_lock(chat_id):
            merge_turn = await session.scalar(
                select(ResponseTurn)
                .where(
                    and_(
                        ResponseTurn.telegram_chat_id == chat_id,
                        ResponseTurn.status == TurnStatus.PENDING.value,
                    )
                )
                .order_by(ResponseTurn.sequence_number.desc())
                .limit(1)
            )
            if merge_turn is None:
                seq = await self._next_sequence(session, chat_id)
                merge_turn = ResponseTurn(
                    telegram_chat_id=chat_id,
                    merged_text="",
                    status=TurnStatus.PENDING.value,
                    sequence_number=seq,
                    debounce_until=now + timedelta(seconds=self.debounce_seconds),
                )
                session.add(merge_turn)
                await session.flush()

            if merge_turn.merged_text:
                merge_turn.merged_text = merge_turn.merged_text + "\n\n" + payload.body_text
            else:
                merge_turn.merged_text = payload.body_text
            merge_turn.debounce_until = now + timedelta(seconds=self.debounce_seconds)
            merge_turn.updated_at = now

            inbound = InboundMessage(
                turn_id=merge_turn.id,
                telegram_chat_id=chat_id,
                telegram_message_id=payload.telegram_message_id,
                dedupe_key=dedupe,
                sender_id=payload.sender_id,
                body_text=payload.body_text,
                raw_payload=payload.raw_payload,
            )
            session.add(inbound)
            await session.flush()
            return EnqueueResult(
                turn_id=merge_turn.id,
                inbound_id=inbound.id,
                dedupe_key=dedupe,
                duplicate=False,
            )

    async def cancel_pending_turn(self, session: AsyncSession, telegram_chat_id: int, *, now: datetime | None = None) -> bool:
        """Mark current PENDING turn as cancelled (admin / supersede)."""
        now = now or _utcnow()
        async with await self._chat_lock(telegram_chat_id):
            turn = await session.scalar(
                select(ResponseTurn).where(
                    and_(
                        ResponseTurn.telegram_chat_id == telegram_chat_id,
                        ResponseTurn.status == TurnStatus.PENDING.value,
                    )
                )
            )
            if turn is None:
                return False
            turn.status = TurnStatus.CANCELLED_BY_NEWER_REQUEST.value
            turn.updated_at = now
            return True

    async def flush_due_turns(self, session: AsyncSession, *, now: datetime) -> int:
        """PENDING + debounce elapsed -> DEBOUNCED (respect FIFO per chat)."""
        stmt = (
            select(ResponseTurn)
            .where(
                and_(
                    ResponseTurn.status == TurnStatus.PENDING.value,
                    ResponseTurn.debounce_until.is_not(None),
                    ResponseTurn.debounce_until <= now,
                )
            )
            .order_by(ResponseTurn.sequence_number)
        )
        rows = (await session.scalars(stmt)).all()
        count = 0
        for turn in rows:
            if await self._blocked_by_lower_sequence(session, turn.telegram_chat_id, turn.sequence_number):
                continue
            turn.status = TurnStatus.DEBOUNCED.value
            turn.updated_at = now
            count += 1
        return count

    async def dispatch_next(
        self,
        session: AsyncSession,
        processor: TurnProcessor,
        *,
        now: datetime | None = None,
    ) -> tuple[UUID, str, str] | None:
        """One DEBOUNCED -> PROCESSING -> terminal via processor. Returns (turn_id, status, merged_text)."""
        now = now or _utcnow()
        stmt = (
            select(ResponseTurn)
            .options(selectinload(ResponseTurn.inbound_messages))
            .where(ResponseTurn.status == TurnStatus.DEBOUNCED.value)
            .order_by(ResponseTurn.sequence_number)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        turn = (await session.scalars(stmt)).first()
        if turn is None:
            return None
        if await self._processing_exists(session, turn.telegram_chat_id):
            return None
        if await self._blocked_by_lower_sequence(session, turn.telegram_chat_id, turn.sequence_number):
            return None
        turn.status = TurnStatus.PROCESSING.value
        turn.updated_at = now
        await session.flush()

        payloads: list[dict[str, Any] | None] = [
            m.raw_payload for m in sorted(turn.inbound_messages, key=lambda m: m.created_at)
        ]
        try:
            terminal = await processor.finalize_turn(
                turn_id=turn.id,
                telegram_chat_id=turn.telegram_chat_id,
                merged_text=turn.merged_text,
                inbound_payloads=payloads,
            )
        except Exception as exc:  # noqa: BLE001 — surface as failed turn
            turn.status = TurnStatus.FAILED_WITH_ERROR.value
            turn.error_message = str(exc)[:4000]
            turn.updated_at = _utcnow()
            await session.flush()
            return (turn.id, turn.status, turn.merged_text)
        if terminal not in TERMINAL:
            raise ValueError(f"processor returned non-terminal status: {terminal}")
        turn.status = terminal
        turn.updated_at = _utcnow()
        await session.flush()
        return (turn.id, terminal, turn.merged_text)

    async def _next_sequence(self, session: AsyncSession, _chat_id: int) -> int:
        """Глобальный монотонный номер очереди — fair dispatch между чатами; per-chat FIFO через блокировки."""
        m = await session.scalar(select(func.max(ResponseTurn.sequence_number)))
        return int(m or 0) + 1

    async def _blocked_by_lower_sequence(self, session: AsyncSession, chat_id: int, seq: int) -> bool:
        q = await session.scalar(
            select(ResponseTurn.id).where(
                and_(
                    ResponseTurn.telegram_chat_id == chat_id,
                    ResponseTurn.sequence_number < seq,
                    ResponseTurn.status.not_in(TERMINAL),
                )
            )
        )
        return q is not None

    async def _processing_exists(self, session: AsyncSession, chat_id: int) -> bool:
        q = await session.scalar(
            select(ResponseTurn.id).where(
                and_(
                    ResponseTurn.telegram_chat_id == chat_id,
                    ResponseTurn.status == TurnStatus.PROCESSING.value,
                )
            )
        )
        return q is not None


async def create_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
