from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pb_studio.api.deps import DbSession, SettingsDep, verify_admin_optional
from pb_studio.summaries.generator import generate_one_summary, generate_pending_summaries_batch
from pb_studio.summaries.planner import get_summary, list_summaries, plan_summary_job
from pb_studio.summaries.schemas import (
    ChatSummaryOut,
    GenerateOneResult,
    GeneratePendingResult,
    PlanSummaryRequest,
    PlanSummaryResponse,
)

router = APIRouter(tags=["summaries"])


@router.get(
    "/summaries",
    response_model=list[ChatSummaryOut],
    dependencies=[Depends(verify_admin_optional)],
)
async def get_summaries(
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    chat_id: UUID | None = Query(default=None, description="Filter by studio_chats.id"),
) -> list[ChatSummaryOut]:
    rows = await list_summaries(session, limit=limit, chat_id=chat_id)
    return [ChatSummaryOut.model_validate(r) for r in rows]


@router.post(
    "/summaries/plan",
    response_model=PlanSummaryResponse,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_summaries_plan(session: DbSession, body: PlanSummaryRequest) -> PlanSummaryResponse:
    try:
        row, created = await plan_summary_job(
            session,
            studio_chat_id=body.studio_chat_id,
            summary_type=body.summary_type,
            period_start=body.period_start,
            period_end=body.period_end,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PlanSummaryResponse(id=row.id, created=created)


@router.post(
    "/summaries/generate-pending",
    response_model=GeneratePendingResult,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_summaries_generate_pending(session: DbSession, settings: SettingsDep) -> GeneratePendingResult:
    raw = await generate_pending_summaries_batch(session, settings)
    return GeneratePendingResult.model_validate(raw)


@router.get(
    "/summaries/{summary_id}",
    response_model=ChatSummaryOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def get_summary_by_id(session: DbSession, summary_id: UUID) -> ChatSummaryOut:
    row = await get_summary(session, summary_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="summary not found")
    return ChatSummaryOut.model_validate(row)


@router.post(
    "/summaries/{summary_id}/generate",
    response_model=GenerateOneResult,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_summaries_generate_one(
    session: DbSession,
    settings: SettingsDep,
    summary_id: UUID,
) -> GenerateOneResult:
    outcome, detail = await generate_one_summary(session, summary_id, settings)
    if outcome == "missing":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="summary not found")
    if outcome == "skipped":
        return GenerateOneResult(id=summary_id, generated=False, reason=detail or "not_pending")
    if outcome == "failed":
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail or "generation failed")
    return GenerateOneResult(id=summary_id, generated=True, reason=None)
