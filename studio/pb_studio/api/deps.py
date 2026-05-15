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


async def verify_memoh_nl_gate_optional(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    token = (settings.studio_memoh_gate_token or "").strip() or (settings.studio_events_ingest_token or "").strip()
    if not token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    got = authorization.removeprefix("Bearer ").strip()
    if got != token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid token")


async def verify_nl_gate_feature_enabled(settings: Settings = Depends(get_settings)) -> None:
    """NL responder gate: reject when STUDIO_NL_COMMANDS_ENABLED is false (single-brain / Memoh-only replies)."""
    if not settings.studio_nl_commands_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="NL gate disabled (STUDIO_NL_COMMANDS_ENABLED=false)",
        )


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


async def verify_kb_enabled(settings: Settings = Depends(get_settings)) -> None:
    if not settings.studio_kb_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_KB_ENABLED is false",
        )


async def verify_kb_embeddings_enabled(settings: Settings = Depends(get_settings)) -> None:
    if not settings.studio_kb_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_KB_ENABLED is false",
        )
    if not settings.studio_kb_embeddings_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_KB_EMBEDDINGS_ENABLED is false",
        )


async def verify_history_import_enabled(settings: Settings = Depends(get_settings)) -> None:
    if not settings.studio_history_import_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_HISTORY_IMPORT_ENABLED is false",
        )


async def verify_kb_rag_enabled(settings: Settings = Depends(get_settings)) -> None:
    if not settings.studio_kb_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_KB_ENABLED is false",
        )
    if not settings.studio_kb_embeddings_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_KB_EMBEDDINGS_ENABLED is false",
        )
    if not settings.studio_kb_rag_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_KB_RAG_ENABLED is false",
        )


DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
QueueServiceDep = Annotated[QueueService, Depends(get_queue_service)]
