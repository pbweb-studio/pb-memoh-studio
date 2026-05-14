from __future__ import annotations

import pb_studio.control_group.models  # noqa: F401 — регистрация таблиц на Base.metadata
import pb_studio.event_mirror.models  # noqa: F401 — регистрация таблиц на Base.metadata
import pb_studio.summaries.models  # noqa: F401 — phase 6a summaries
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pb_studio.core.config import get_settings
from pb_studio.response_queue.models import Base
from pb_studio.response_queue.service import QueueService, create_tables


@pytest.fixture(autouse=True)
def _isolate_studio_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сброс env, влияющих на admin/Telegram/summary delivery, между тестами (изоляция от порядка запуска)."""
    for key in (
        "STUDIO_ADMIN_TOKEN",
        "STUDIO_SUMMARY_DELIVERY_ENABLED",
        "STUDIO_SUMMARY_GENERATION_ENABLED",
        "TELEGRAM_BOT_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await create_tables(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
