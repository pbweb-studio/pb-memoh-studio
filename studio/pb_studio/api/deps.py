from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.response_queue.service import QueueService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_queue_service() -> QueueService:
    return QueueService()


async def verify_events_ingest_optional(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    token = settings.studio_events_ingest_token
    if not token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    got = authorization.removeprefix("Bearer ").strip()
    if got != token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid token")


async def verify_admin_optional(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    token = settings.studio_admin_token
    if not token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    got = authorization.removeprefix("Bearer ").strip()
    if got != token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid token")


DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
QueueServiceDep = Annotated[QueueService, Depends(get_queue_service)]
