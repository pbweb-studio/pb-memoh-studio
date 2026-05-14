from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from pb_studio.api.deps import DbSession, SettingsDep, verify_admin_optional, verify_history_import_enabled
from pb_studio.history_import.schemas import HistoryImportJobOut, HistoryImportTelegramJsonOut
from pb_studio.history_import import service as history_import_service

router = APIRouter(
    prefix="/history-import",
    tags=["history-import"],
    dependencies=[Depends(verify_admin_optional), Depends(verify_history_import_enabled)],
)


@router.post("/telegram-json", response_model=HistoryImportTelegramJsonOut, status_code=status.HTTP_201_CREATED)
async def post_history_import_telegram_json(
    session: DbSession,
    settings: SettingsDep,
    file: UploadFile = File(..., description="Telegram Desktop export JSON"),
) -> HistoryImportTelegramJsonOut:
    raw = await file.read()
    max_b = int(settings.studio_history_import_max_bytes)
    if len(raw) > max_b:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"file exceeds STUDIO_HISTORY_IMPORT_MAX_BYTES ({max_b})",
        )
    job = await history_import_service.run_telegram_desktop_json_import(
        session,
        settings,
        raw_bytes=raw,
        file_name=file.filename,
    )
    return HistoryImportTelegramJsonOut(job=HistoryImportJobOut.model_validate(job))


@router.get("/jobs", response_model=list[HistoryImportJobOut])
async def get_history_import_jobs(
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[HistoryImportJobOut]:
    rows = await history_import_service.list_jobs(session, limit=limit)
    return [HistoryImportJobOut.model_validate(r) for r in rows]


@router.get("/jobs/{job_id}", response_model=HistoryImportJobOut)
async def get_history_import_job(session: DbSession, job_id: UUID) -> HistoryImportJobOut:
    row = await history_import_service.get_job(session, job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    return HistoryImportJobOut.model_validate(row)
