from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from pb_studio.api.deps import DbSession, SettingsDep, verify_admin_optional
from pb_studio.control_group.schemas import DeliverPendingResult, SystemNotificationAdminOut
from pb_studio.control_group.system_notification_delivery import deliver_pending_batch, list_system_notifications

router = APIRouter(tags=["notifications"])


@router.get(
    "/notifications/system",
    response_model=list[SystemNotificationAdminOut],
    dependencies=[Depends(verify_admin_optional)],
)
async def get_system_notifications(
    session: DbSession,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SystemNotificationAdminOut]:
    rows = await list_system_notifications(session, status=status, limit=limit)
    return [SystemNotificationAdminOut.model_validate(r) for r in rows]


@router.post(
    "/notifications/system/deliver-pending",
    response_model=DeliverPendingResult,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_deliver_pending_system_notifications(session: DbSession, settings: SettingsDep) -> DeliverPendingResult:
    raw = await deliver_pending_batch(session, settings=settings)
    return DeliverPendingResult.model_validate(raw)
