from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_group.constants import ChatRole
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.response_queue.models import Base
from pb_studio.summaries.constants import SummaryStatus, SummaryType
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.planner import plan_daily_chat_summaries, plan_summary_job


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


def _msg(update_id: int, chat_id: int = -9001) -> dict:
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


@pytest.mark.asyncio
async def test_plan_pending_summary_job(sum_client):
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(91001))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -9001))
    assert chat is not None
    chat.chat_role = ChatRole.CLIENT_CHAT.value
    await session.commit()

    p0 = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
    p1 = datetime(2024, 6, 2, 0, 0, tzinfo=timezone.utc)
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=10,
            date=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
            text="a",
            raw_message={"x": 1},
        )
    )
    await session.commit()

    row1, created1 = await plan_summary_job(
        session,
        studio_chat_id=chat.id,
        summary_type=SummaryType.DAILY,
        period_start=p0,
        period_end=p1,
    )
    assert created1 is True
    assert row1.status == SummaryStatus.PENDING
    assert row1.chat_id == chat.id
    assert row1.chat_role == ChatRole.CLIENT_CHAT.value
    assert row1.source_event_count == 1
    await session.commit()

    row2, created2 = await plan_summary_job(
        session,
        studio_chat_id=chat.id,
        summary_type=SummaryType.DAILY,
        period_start=p0,
        period_end=p1,
    )
    assert created2 is False
    assert row2.id == row1.id
    n = await session.scalar(select(func.count()).select_from(StudioChatSummary))
    assert n == 1


@pytest.mark.asyncio
async def test_plan_daily_idempotent(sum_client):
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(91002, chat_id=-9002))
    ref = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    r1 = await plan_daily_chat_summaries(session, reference_utc=ref)
    await session.commit()
    assert r1["jobs_created"] >= 1
    r2 = await plan_daily_chat_summaries(session, reference_utc=ref)
    await session.commit()
    assert r2["skipped_duplicates"] >= 1
    assert r2["jobs_created"] == 0


@pytest.mark.asyncio
async def test_summaries_admin_enforced(monkeypatch, sum_client):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm-6a")
    get_settings.cache_clear()
    client, _ = sum_client
    r = await client.get("/summaries")
    assert r.status_code == 401
    r2 = await client.get("/summaries", headers={"Authorization": "Bearer adm-6a"})
    assert r2.status_code == 200
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_summaries_plan_api(monkeypatch, sum_client):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm-plan")
    get_settings.cache_clear()
    client, session = sum_client
    await client.post("/events/telegram", json=_msg(91003, chat_id=-9003))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -9003))
    p0 = "2024-07-01T00:00:00+00:00"
    p1 = "2024-07-02T00:00:00+00:00"
    r = await client.post(
        "/summaries/plan",
        headers={"Authorization": "Bearer adm-plan"},
        json={
            "studio_chat_id": str(chat.id),
            "summary_type": "manual",
            "period_start": p0,
            "period_end": p1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    r2 = await client.post(
        "/summaries/plan",
        headers={"Authorization": "Bearer adm-plan"},
        json={
            "studio_chat_id": str(chat.id),
            "summary_type": "manual",
            "period_start": p0,
            "period_end": p1,
        },
    )
    assert r2.json()["created"] is False
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_summary_not_found(monkeypatch, sum_client):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "x")
    get_settings.cache_clear()
    client, _ = sum_client
    rid = uuid4()
    r = await client.get(f"/summaries/{rid}", headers={"Authorization": "Bearer x"})
    assert r.status_code == 404
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_planner_no_httpx(monkeypatch, sum_client):
    """Regression: summaries planner must not open outbound HTTP (no Telegram / OpenAI here)."""
    import httpx

    client, session = sum_client
    await client.post("/events/telegram", json=_msg(91004, chat_id=-9004))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -9004))

    async def boom(*_a, **_k):
        raise AssertionError("httpx must not be used by summary planner")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    p0 = datetime(2024, 8, 1, tzinfo=timezone.utc)
    p1 = p0 + timedelta(days=1)
    await plan_summary_job(
        session,
        studio_chat_id=chat.id,
        summary_type=SummaryType.WEEKLY,
        period_start=p0,
        period_end=p1,
    )
    await session.commit()


def test_celery_plan_daily_registered():
    import pb_studio.worker.tasks  # noqa: F401 — registers Celery tasks
    from pb_studio.celery_app import celery_app

    assert "pb_studio.worker.plan_daily_chat_summaries" in celery_app.tasks


def test_celery_plan_daily_task_invokes_runner(monkeypatch):
    import inspect

    def fake_run(coro):
        assert inspect.iscoroutine(coro)
        assert coro.__name__ == "run_plan_daily_standalone"
        coro.close()
        return {
            "chats_examined": 0,
            "jobs_created": 0,
            "skipped_duplicates": 0,
            "period_start": 0,
            "period_end": 0,
        }

    monkeypatch.setattr("pb_studio.worker.tasks.asyncio.run", fake_run)
    from pb_studio.worker.tasks import plan_daily_chat_summaries

    out = plan_daily_chat_summaries()
    assert out["jobs_created"] == 0