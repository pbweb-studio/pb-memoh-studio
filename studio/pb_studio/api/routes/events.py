from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from pb_studio.api.deps import DbSession, QueueServiceDep, SettingsDep, verify_events_ingest_optional
from pb_studio.event_mirror.schemas import TelegramEventIngestResponse
from pb_studio.event_mirror.service import ingest_telegram_update

router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "/telegram",
    response_model=TelegramEventIngestResponse,
    dependencies=[Depends(verify_events_ingest_optional)],
)
async def post_telegram_event(
    body: dict[str, Any],
    session: DbSession,
    settings: SettingsDep,
    queue: QueueServiceDep,
) -> TelegramEventIngestResponse:
    try:
        raw, duplicate, enqueue = await ingest_telegram_update(
            session,
            body,
            queue=queue if settings.studio_mirror_enqueue_user_messages else None,
            mirror_enqueue_user_messages=settings.studio_mirror_enqueue_user_messages,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TelegramEventIngestResponse(
        ok=True,
        telegram_raw_update_id=raw.id,
        duplicate=duplicate,
        enqueue=enqueue,
    )
