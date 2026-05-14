from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pb_studio.api.deps import DbSession, verify_admin_optional
from pb_studio.project_digests.delivery import deliver_project_digest_by_id, deliver_pending_project_digests_batch
from pb_studio.project_digests.schemas import DeliverPendingProjectDigestsResult, ProjectDigestOut, ProjectDigestPeriodBody
from pb_studio.project_digests.service import get_digest, list_project_digests

router = APIRouter(tags=["project-digests"])


@router.get(
    "/project-digests/{digest_id}",
    response_model=ProjectDigestOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def get_project_digest_by_id(session: DbSession, digest_id: UUID) -> ProjectDigestOut:
    row = await get_digest(session, digest_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="digest not found")
    return ProjectDigestOut.model_validate(row)


@router.post(
    "/project-digests/{digest_id}/deliver-control-group",
    response_model=ProjectDigestOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_deliver_project_digest(session: DbSession, digest_id: UUID) -> ProjectDigestOut:
    from pb_studio.core.config import get_settings

    settings = get_settings()
    try:
        row, _ = await deliver_project_digest_by_id(session, digest_id, settings)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProjectDigestOut.model_validate(row)


@router.post(
    "/project-digests/deliver-pending",
    response_model=DeliverPendingProjectDigestsResult,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_deliver_pending_project_digests(session: DbSession) -> DeliverPendingProjectDigestsResult:
    from pb_studio.core.config import get_settings

    settings = get_settings()
    raw = await deliver_pending_project_digests_batch(session, settings)
    return DeliverPendingProjectDigestsResult.model_validate(raw)
