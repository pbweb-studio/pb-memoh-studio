from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_group.constants import ChatRole
from pb_studio.core.config import Settings, get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.response_queue.models import Base
from pb_studio.summaries import generator as gen_mod
from pb_studio.summaries.constants import SummaryStatus, SummaryType
from pb_studio.summaries.generator import EMPTY_PERIOD_TEXT, generate_pending_summaries_batch
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.planner import plan_summary_job


@pytest_asyncio.fixture
async def sum_engine():
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
async def sum_client(sum_engine):
    factory = async_sessionmaker(sum_engine, class_=AsyncSession, expire_on_commit=False)
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


def _msg(update_id: int, chat_id: int = -91001) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "T"},
            "from": {"id": 42, "is_bot": False, "first_name": "U"},
            "text": "hello",
        },
    }


def _settings_gen_enabled(**kwargs) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://x:x@127.0.0.1:9/x",
        "redis_url": "redis://127.0.0.1:9/0",
        "celery_broker_url": "redis://127.0.0.1:9/1",
        "studio_summary_generation_enabled": True,
        "studio_summary_max_source_messages": 200,
        "studio_summary_max_bullets": 20,
    }
    base.update(kwargs)
    return Settings.model_validate(base)


@pytest.mark.asyncio
async def test_generate_pending_sets_generated_and_text(sum_client, monkeypatch):
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(92001))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91001))
    chat.chat_role = ChatRole.CLIENT_CHAT.value
    p0 = datetime(2024, 6, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=50,
            date=datetime(2024, 6, 1, 15, 0, tzinfo=timezone.utc),
            text="visible line",
            raw_message={"from": {"id": 99}, "text": "visible line", "message_id": 50},
        )
    )
    await session.commit()
    await plan_summary_job(
        session,
        studio_chat_id=chat.id,
        summary_type=SummaryType.MANUAL,
        period_start=p0,
        period_end=p1,
    )
    await session.commit()

    s = _settings_gen_enabled()
    out = await generate_pending_summaries_batch(session, s)
    await session.commit()
    assert out["generated"] == 1
    row = await session.scalar(select(StudioChatSummary))
    assert row.status == SummaryStatus.GENERATED
    assert row.summary_text and "visible line" in row.summary_text
    assert row.source_event_count == 1
    assert row.generated_at is not None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_empty_period_generated_exact_text(sum_client, monkeypatch):
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(92002, chat_id=-91002))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91002))
    p0 = datetime(2099, 1, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    await plan_summary_job(
        session,
        studio_chat_id=chat.id,
        summary_type=SummaryType.MANUAL,
        period_start=p0,
        period_end=p1,
    )
    await session.commit()
    s = _settings_gen_enabled()
    await generate_pending_summaries_batch(session, s)
    await session.commit()
    row = await session.scalar(select(StudioChatSummary))
    assert row.summary_text == EMPTY_PERIOD_TEXT
    assert row.status == SummaryStatus.GENERATED
    assert row.source_event_count == 0
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_second_batch_does_not_regenerate(sum_client, monkeypatch):
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(92003, chat_id=-91003))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91003))
    p0 = datetime(2024, 9, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=2,
            date=datetime(2024, 9, 1, 10, 0, tzinfo=timezone.utc),
            text="once",
            raw_message={"from": {"id": 1}, "text": "once"},
        )
    )
    await session.commit()
    await plan_summary_job(session, studio_chat_id=chat.id, summary_type=SummaryType.MANUAL, period_start=p0, period_end=p1)
    await session.commit()
    s = _settings_gen_enabled()
    first = await generate_pending_summaries_batch(session, s)
    await session.commit()
    assert first["generated"] == 1
    text1 = (await session.scalar(select(StudioChatSummary))).summary_text
    second = await generate_pending_summaries_batch(session, s)
    await session.commit()
    assert second["examined"] == 0
    assert second["generated"] == 0
    text2 = (await session.scalar(select(StudioChatSummary))).summary_text
    assert text1 == text2
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_batch_isolation_one_failure(sum_client, monkeypatch):
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(92004, chat_id=-91004))
    await client.post("/events/telegram", json=_msg(92005, chat_id=-91005))
    c1 = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91004))
    c2 = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91005))
    p0 = datetime(2024, 10, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    for idx, c in enumerate((c1, c2), start=2):
        session.add(
            StudioMessage(
                chat_id=c.id,
                telegram_message_id=idx,
                date=datetime(2024, 10, 1, 10, 0, tzinfo=timezone.utc),
                text="x",
                raw_message={"from": {"id": 1}, "text": "x"},
            )
        )
    await session.commit()
    await plan_summary_job(session, studio_chat_id=c1.id, summary_type=SummaryType.MANUAL, period_start=p0, period_end=p1)
    await plan_summary_job(session, studio_chat_id=c2.id, summary_type=SummaryType.MANUAL, period_start=p0, period_end=p1)
    await session.commit()

    orig = gen_mod.apply_generation_to_row
    counter = {"n": 0}

    async def wrap(sess, row, settings):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("simulated failure")
        return await orig(sess, row, settings)

    monkeypatch.setattr(gen_mod, "apply_generation_to_row", wrap)
    s = _settings_gen_enabled()
    out = await generate_pending_summaries_batch(session, s)
    await session.commit()
    assert out["examined"] == 2
    assert out["generated"] == 1
    assert out["failed"] == 1
    statuses = {r.status for r in (await session.scalars(select(StudioChatSummary))).all()}
    assert SummaryStatus.GENERATED in statuses
    assert SummaryStatus.FAILED in statuses
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_generate_api_admin(monkeypatch, sum_client):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "g6b")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(92006, chat_id=-91006))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91006))
    p0 = datetime(2024, 11, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    await plan_summary_job(session, studio_chat_id=chat.id, summary_type=SummaryType.MANUAL, period_start=p0, period_end=p1)
    await session.commit()
    r0 = await client.post("/summaries/generate-pending")
    assert r0.status_code == 401
    r = await client.post("/summaries/generate-pending", headers={"Authorization": "Bearer g6b"})
    assert r.status_code == 200
    assert r.json()["generated"] == 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_generate_one_skips_already_generated(monkeypatch, sum_client):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "g6b2")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(92007, chat_id=-91007))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91007))
    p0 = datetime(2024, 12, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    row, _ = await plan_summary_job(session, studio_chat_id=chat.id, summary_type=SummaryType.MANUAL, period_start=p0, period_end=p1)
    await session.commit()
    await generate_pending_summaries_batch(session, _settings_gen_enabled())
    await session.commit()
    r = await client.post(f"/summaries/{row.id}/generate", headers={"Authorization": "Bearer g6b2"})
    assert r.status_code == 200
    assert r.json()["generated"] is False
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_no_httpx_used(monkeypatch, sum_client):
    import httpx

    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(92008, chat_id=-91008))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91008))
    p0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    await plan_summary_job(session, studio_chat_id=chat.id, summary_type=SummaryType.MANUAL, period_start=p0, period_end=p1)
    await session.commit()

    async def boom(*_a, **_k):
        raise AssertionError("no httpx in template generation")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    await generate_pending_summaries_batch(session, _settings_gen_enabled())
    await session.commit()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_telegram_send_not_called(monkeypatch, sum_client):
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    from pb_studio.control_group import telegram_outbound as tg

    mock = AsyncMock(side_effect=AssertionError("sendMessage must not be used for summaries"))
    monkeypatch.setattr(tg, "telegram_send_message", mock)
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(92009, chat_id=-91009))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -91009))
    p0 = datetime(2025, 2, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    await plan_summary_job(session, studio_chat_id=chat.id, summary_type=SummaryType.MANUAL, period_start=p0, period_end=p1)
    await session.commit()
    await generate_pending_summaries_batch(session, _settings_gen_enabled())
    await session.commit()
    mock.assert_not_called()
    get_settings.cache_clear()


def test_celery_generate_pending_registered():
    import pb_studio.worker.tasks  # noqa: F401
    from pb_studio.celery_app import celery_app

    assert "pb_studio.worker.generate_pending_chat_summaries" in celery_app.tasks


def test_celery_generate_task_invokes_runner(monkeypatch):
    import inspect

    def fake_run(coro):
        assert inspect.iscoroutine(coro)
        assert coro.__name__ == "run_generate_pending_standalone"
        coro.close()
        return {"examined": 0, "generated": 0, "failed": 0, "skipped_disabled": 0, "skipped_not_pending": 0}

    monkeypatch.setattr("pb_studio.worker.tasks.asyncio.run", fake_run)
    from pb_studio.worker.tasks import generate_pending_chat_summaries

    out = generate_pending_chat_summaries()
    assert out["generated"] == 0
