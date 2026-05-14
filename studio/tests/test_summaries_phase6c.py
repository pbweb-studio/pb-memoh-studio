from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

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
from pb_studio.core.config import get_settings
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.response_queue.models import Base
from pb_studio.summaries.constants import SummaryStatus, SummaryType
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.planner import plan_summary_job, utc_day_bounds


@pytest_asyncio.fixture
async def prod_engine():
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
async def prod_client(prod_engine):
    factory = async_sessionmaker(prod_engine, class_=AsyncSession, expire_on_commit=False)
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


def _msg(update_id: int, chat_id: int = -92001) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "ProdT"},
            "from": {"id": 42, "is_bot": False, "first_name": "U"},
            "text": "hello",
        },
    }


@pytest.mark.asyncio
async def test_today_creates_and_generates(prod_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    fixed = datetime(2025, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)

    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93001))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92001))
    p0, p1 = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=3),
            text="today line",
            raw_message={"from": {"id": 7}, "text": "today line"},
        )
    )
    await session.commit()

    r = await client.post(f"/summaries/chat/{chat.id}/today", headers={"Authorization": "Bearer p6c"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "generated"
    assert "today line" in (body.get("summary_text") or "")
    assert body["summary_type"] == SummaryType.DAILY
    n = await session.scalar(select(func.count()).select_from(StudioChatSummary))
    assert n == 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_today_idempotent(prod_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    fixed = datetime(2025, 4, 10, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)

    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93002, chat_id=-92002))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92002))
    p0, _ = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=1),
            text="x",
            raw_message={"from": {"id": 1}, "text": "x"},
        )
    )
    await session.commit()

    r1 = await client.post(f"/summaries/chat/{chat.id}/today", headers={"Authorization": "Bearer p6c"})
    r2 = await client.post(f"/summaries/chat/{chat.id}/today", headers={"Authorization": "Bearer p6c"})
    assert r1.json()["id"] == r2.json()["id"]
    n = await session.scalar(select(func.count()).select_from(StudioChatSummary))
    assert n == 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_pending_regenerates_on_second_post(prod_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    fixed = datetime(2025, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)

    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93003, chat_id=-92003))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92003))
    p0, p1 = utc_day_bounds(fixed.date())
    await plan_summary_job(session, studio_chat_id=chat.id, summary_type=SummaryType.DAILY, period_start=p0, period_end=p1)
    await session.commit()

    r = await client.post(f"/summaries/chat/{chat.id}/today", headers={"Authorization": "Bearer p6c"})
    assert r.status_code == 200
    assert r.json()["status"] == "generated"
    assert r.json()["summary_text"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_yesterday_endpoint(prod_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    fixed = datetime(2025, 6, 20, 15, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)

    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93004, chat_id=-92004))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92004))
    y = fixed.date() - timedelta(days=1)
    p0, p1 = utc_day_bounds(y)
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=2),
            text="yest",
            raw_message={"from": {"id": 3}, "text": "yest"},
        )
    )
    await session.commit()

    r = await client.post(f"/summaries/chat/{chat.id}/yesterday", headers={"Authorization": "Bearer p6c"})
    assert r.status_code == 200
    assert r.json()["summary_type"] == SummaryType.DAILY
    assert "yest" in (r.json().get("summary_text") or "")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_period_endpoint(prod_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93005, chat_id=-92005))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92005))
    p0 = datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    p1 = datetime(2025, 7, 2, 0, 0, 0, tzinfo=timezone.utc)
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=2,
            date=datetime(2025, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
            text="periodmsg",
            raw_message={"from": {"id": 2}, "text": "periodmsg"},
        )
    )
    await session.commit()

    r = await client.post(
        f"/summaries/chat/{chat.id}/period",
        headers={"Authorization": "Bearer p6c"},
        json={"period_start": p0.isoformat(), "period_end": p1.isoformat()},
    )
    assert r.status_code == 200
    assert r.json()["summary_type"] == SummaryType.MANUAL
    assert "periodmsg" in (r.json().get("summary_text") or "")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_latest_returns_newest_generated(prod_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93006, chat_id=-92006))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92006))
    a0 = datetime(2025, 8, 1, tzinfo=timezone.utc)
    a1 = datetime(2025, 8, 2, tzinfo=timezone.utc)
    b0 = datetime(2025, 8, 3, tzinfo=timezone.utc)
    b1 = datetime(2025, 8, 4, tzinfo=timezone.utc)
    for mid, t0, txt in ((2, a0, "older"), (3, b0, "newer")):
        session.add(
            StudioMessage(
                chat_id=chat.id,
                telegram_message_id=mid,
                date=t0 + timedelta(hours=1),
                text=txt,
                raw_message={"from": {"id": 1}, "text": txt},
            )
        )
    await session.commit()
    await client.post(
        f"/summaries/chat/{chat.id}/period",
        headers={"Authorization": "Bearer p6c"},
        json={"period_start": a0.isoformat(), "period_end": a1.isoformat()},
    )
    await client.post(
        f"/summaries/chat/{chat.id}/period",
        headers={"Authorization": "Bearer p6c"},
        json={"period_start": b0.isoformat(), "period_end": b1.isoformat()},
    )
    r = await client.get(f"/summaries/chat/{chat.id}/latest", headers={"Authorization": "Bearer p6c"})
    assert r.status_code == 200
    assert "newer" in (r.json().get("summary_text") or "")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_product_requires_admin(prod_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93007, chat_id=-92007))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92007))
    fixed = datetime(2025, 9, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)
    p0, _ = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=1),
            text="z",
            raw_message={"from": {"id": 1}, "text": "z"},
        )
    )
    await session.commit()
    r = await client.post(f"/summaries/chat/{chat.id}/today")
    assert r.status_code == 401
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_failed_period_returns_409(prod_client, monkeypatch):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    fixed = datetime(2025, 10, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)

    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93008, chat_id=-92008))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92008))
    p0, p1 = utc_day_bounds(fixed.date())
    row, _ = await plan_summary_job(session, studio_chat_id=chat.id, summary_type=SummaryType.DAILY, period_start=p0, period_end=p1)
    row.status = SummaryStatus.FAILED
    row.last_error = "x"
    await session.commit()

    r = await client.post(f"/summaries/chat/{chat.id}/today", headers={"Authorization": "Bearer p6c"})
    assert r.status_code == 409
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_no_httpx_no_telegram(prod_client, monkeypatch):
    import httpx
    from pb_studio.control_group import telegram_outbound as tg

    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "p6c")
    monkeypatch.setenv("STUDIO_SUMMARY_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    fixed = datetime(2025, 11, 11, tzinfo=timezone.utc)
    monkeypatch.setattr("pb_studio.summaries.product.summaries_clock", lambda: fixed)

    async def boom(*_a, **_k):
        raise AssertionError("httpx")

    mock_send = AsyncMock(side_effect=AssertionError("telegram"))
    monkeypatch.setattr(httpx, "AsyncClient", boom)
    monkeypatch.setattr(tg, "telegram_send_message", mock_send)

    client, session = prod_client
    await client.post("/events/telegram", json=_msg(93009, chat_id=-92009))
    chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == -92009))
    p0, _ = utc_day_bounds(fixed.date())
    session.add(
        StudioMessage(
            chat_id=chat.id,
            telegram_message_id=2,
            date=p0 + timedelta(hours=1),
            text="ok",
            raw_message={"from": {"id": 1}, "text": "ok"},
        )
    )
    await session.commit()
    r = await client.post(f"/summaries/chat/{chat.id}/today", headers={"Authorization": "Bearer p6c"})
    assert r.status_code == 200
    mock_send.assert_not_called()
    get_settings.cache_clear()
