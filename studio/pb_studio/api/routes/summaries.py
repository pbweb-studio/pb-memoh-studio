from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pb_studio.api.deps import DbSession, SettingsDep, verify_admin_optional
from pb_studio.summaries.models import StudioChatSummary
from pb_studio.summaries.constants import SummaryType
from pb_studio.summaries.generator import generate_one_summary, generate_pending_summaries_batch
from pb_studio.summaries.planner import get_summary, list_summaries, plan_summary_job
from pb_studio.summaries.product import (
    ensure_chat_summary_for_period,
    get_latest_generated_for_chat,
    utc_today_period,
    utc_yesterday_period,
)
from pb_studio.summaries.summary_delivery import (
    deliver_pending_summaries_batch,
    deliver_summary_to_control_group_by_id,
)
from pb_studio.summaries.schemas import (
    ChatSummaryOut,
    ChatSummaryProductOut,
    DeliverPendingSummariesResult,
    DeliverSummaryResult,
    GenerateOneResult,
    GeneratePendingResult,
    PeriodSummaryBody,
    PlanSummaryRequest,
    PlanSummaryResponse,
)

router = APIRouter(tags=["summaries"])


def _to_product(row: StudioChatSummary) -> ChatSummaryProductOut:
    return ChatSummaryProductOut(
        id=row.id,
        chat_id=row.chat_id,
        chat_role=row.chat_role,
        summary_type=row.summary_type,
        period_start=row.period_start,
        period_end=row.period_end,
        status=row.status,
        source_event_count=row.source_event_count,
        summary_text=row.summary_text,
        generated_at=row.generated_at,
    )


@router.get(
    "/summaries",
    response_model=list[ChatSummaryOut],
    dependencies=[Depends(verify_admin_optional)],
)
async def get_summaries(
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    chat_id: UUID | None = Query(default=None, description="Filter by studio_chats.id"),
    delivery_status: str | None = Query(default=None, description="Filter by delivery_status (фаза 6d)"),
) -> list[ChatSummaryOut]:
    rows = await list_summaries(session, limit=limit, chat_id=chat_id, delivery_status=delivery_status)
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


@router.post(
    "/summaries/deliver-pending",
    response_model=DeliverPendingSummariesResult,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_summaries_deliver_pending(session: DbSession, settings: SettingsDep) -> DeliverPendingSummariesResult:
    raw = await deliver_pending_summaries_batch(session, settings)
    return DeliverPendingSummariesResult.model_validate(raw)


def _product_http(exc: ValueError) -> HTTPException:
    msg = str(exc)
    if "status failed" in msg.lower():
        return HTTPException(status.HTTP_409_CONFLICT, detail=msg)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg)


@router.post(
    "/summaries/chat/{chat_id}/today",
    response_model=ChatSummaryProductOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_summaries_chat_today(
    session: DbSession,
    settings: SettingsDep,
    chat_id: UUID,
) -> ChatSummaryProductOut:
    p0, p1 = utc_today_period()
    try:
        row = await ensure_chat_summary_for_period(
            session,
            studio_chat_id=chat_id,
            summary_type=SummaryType.DAILY,
            period_start=p0,
            period_end=p1,
            settings=settings,
        )
    except ValueError as exc:
        raise _product_http(exc) from exc
    return _to_product(row)


@router.post(
    "/summaries/chat/{chat_id}/yesterday",
    response_model=ChatSummaryProductOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_summaries_chat_yesterday(
    session: DbSession,
    settings: SettingsDep,
    chat_id: UUID,
) -> ChatSummaryProductOut:
    p0, p1 = utc_yesterday_period()
    try:
        row = await ensure_chat_summary_for_period(
            session,
            studio_chat_id=chat_id,
            summary_type=SummaryType.DAILY,
            period_start=p0,
            period_end=p1,
            settings=settings,
        )
    except ValueError as exc:
        raise _product_http(exc) from exc
    return _to_product(row)


@router.post(
    "/summaries/chat/{chat_id}/period",
    response_model=ChatSummaryProductOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_summaries_chat_period(
    session: DbSession,
    settings: SettingsDep,
    chat_id: UUID,
    body: PeriodSummaryBody,
) -> ChatSummaryProductOut:
    try:
        row = await ensure_chat_summary_for_period(
            session,
            studio_chat_id=chat_id,
            summary_type=SummaryType.MANUAL,
            period_start=body.period_start,
            period_end=body.period_end,
            settings=settings,
        )
    except ValueError as exc:
        raise _product_http(exc) from exc
    return _to_product(row)


@router.get(
    "/summaries/chat/{chat_id}/latest",
    response_model=ChatSummaryProductOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def get_summaries_chat_latest(session: DbSession, chat_id: UUID) -> ChatSummaryProductOut:
    row = await get_latest_generated_for_chat(session, studio_chat_id=chat_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no generated summary for this chat")
    return _to_product(row)


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


@router.post(
    "/summaries/{summary_id}/deliver-control-group",
    response_model=DeliverSummaryResult,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_summaries_deliver_control_group(
    session: DbSession,
    settings: SettingsDep,
    summary_id: UUID,
) -> DeliverSummaryResult:
    try:
        row, reason = await deliver_summary_to_control_group_by_id(session, summary_id, settings)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DeliverSummaryResult(
        id=row.id,
        delivery_status=row.delivery_status,
        telegram_message_id=row.telegram_message_id,
        delivered_at=row.delivered_at,
        reason=reason,
    )
