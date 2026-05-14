from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pb_studio.api.deps import DbSession, verify_admin_optional
from pb_studio.summaries.planner import get_summary, list_summaries, plan_summary_job
from pb_studio.summaries.schemas import ChatSummaryOut, PlanSummaryRequest, PlanSummaryResponse

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
