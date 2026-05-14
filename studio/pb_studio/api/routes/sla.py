from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pb_studio.api.deps import DbSession, SettingsDep, verify_admin_optional
from pb_studio.sla.detector import run_sla_detection_cycle
from pb_studio.sla.schemas import (
    SlaDetectResponse,
    SlaIncidentOut,
    SlaManualNotifyResponse,
    SlaNotificationEventOut,
    SlaPolicyCreate,
    SlaPolicyMuteBody,
    SlaPolicyOut,
    SlaPolicyPatch,
)
from pb_studio.sla.service import (
    acknowledge_incident,
    create_sla_policy,
    list_sla_incidents,
    list_sla_notification_events,
    list_sla_policies,
    mute_sla_policy,
    patch_sla_policy_fields,
    resolve_incident,
    sla_manual_notify,
    unmute_sla_policy,
)

router = APIRouter(prefix="/sla", tags=["sla"])


@router.get("/incidents", response_model=list[SlaIncidentOut], dependencies=[Depends(verify_admin_optional)])
async def get_sla_incidents(
    session: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    chat_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SlaIncidentOut]:
    rows = await list_sla_incidents(
        session, status=status_filter, severity=severity, chat_id=chat_id, limit=limit
    )
    return [SlaIncidentOut.model_validate(r) for r in rows]


@router.get(
    "/notification-events",
    response_model=list[SlaNotificationEventOut],
    dependencies=[Depends(verify_admin_optional)],
)
async def get_sla_notification_events(
    session: DbSession,
    incident_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SlaNotificationEventOut]:
    rows = await list_sla_notification_events(session, incident_id=incident_id, limit=limit)
    return [SlaNotificationEventOut.model_validate(r) for r in rows]


@router.post("/detect", response_model=SlaDetectResponse, dependencies=[Depends(verify_admin_optional)])
async def post_sla_detect(session: DbSession, settings: SettingsDep) -> SlaDetectResponse:
    raw = await run_sla_detection_cycle(session, settings)
    return SlaDetectResponse.model_validate(raw)


@router.post(
    "/incidents/{incident_id}/notify",
    response_model=SlaManualNotifyResponse,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_sla_incident_notify(
    session: DbSession, settings: SettingsDep, incident_id: UUID
) -> SlaManualNotifyResponse:
    raw = await sla_manual_notify(session, settings, incident_id)
    return SlaManualNotifyResponse.model_validate(raw)


@router.post(
    "/incidents/{incident_id}/ack",
    response_model=SlaIncidentOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_sla_incident_ack(session: DbSession, incident_id: UUID) -> SlaIncidentOut:
    row = await acknowledge_incident(session, incident_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incident not found")
    return SlaIncidentOut.model_validate(row)


@router.post(
    "/incidents/{incident_id}/resolve",
    response_model=SlaIncidentOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_sla_incident_resolve(session: DbSession, incident_id: UUID) -> SlaIncidentOut:
    row = await resolve_incident(session, incident_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incident not found")
    return SlaIncidentOut.model_validate(row)


@router.get("/policies", response_model=list[SlaPolicyOut], dependencies=[Depends(verify_admin_optional)])
async def get_sla_policies(session: DbSession) -> list[SlaPolicyOut]:
    rows = await list_sla_policies(session)
    return [SlaPolicyOut.model_validate(r) for r in rows]


@router.post("/policies", response_model=SlaPolicyOut, dependencies=[Depends(verify_admin_optional)])
async def post_sla_policy(session: DbSession, body: SlaPolicyCreate) -> SlaPolicyOut:
    row = await create_sla_policy(
        session,
        chat_role=body.chat_role,
        first_response_minutes=body.first_response_minutes,
        followup_minutes=body.followup_minutes,
        is_active=body.is_active,
        policy_tz=body.policy_tz,
        working_days_json=body.working_days_json,
        working_hours_start=body.working_hours_start,
        working_hours_end=body.working_hours_end,
        holidays_json=body.holidays_json,
    )
    return SlaPolicyOut.model_validate(row)


@router.patch("/policies/{policy_id}", response_model=SlaPolicyOut, dependencies=[Depends(verify_admin_optional)])
async def patch_sla_policy_route(session: DbSession, policy_id: UUID, body: SlaPolicyPatch) -> SlaPolicyOut:
    updates = body.model_dump(exclude_unset=True)
    row = await patch_sla_policy_fields(session, policy_id, updates)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="policy not found")
    return SlaPolicyOut.model_validate(row)


@router.post("/policies/{policy_id}/mute", response_model=SlaPolicyOut, dependencies=[Depends(verify_admin_optional)])
async def post_sla_policy_mute(session: DbSession, policy_id: UUID, body: SlaPolicyMuteBody) -> SlaPolicyOut:
    row = await mute_sla_policy(
        session,
        policy_id,
        muted_until=body.muted_until,
        mute_reason=body.mute_reason,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="policy not found")
    return SlaPolicyOut.model_validate(row)


@router.post(
    "/policies/{policy_id}/unmute",
    response_model=SlaPolicyOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_sla_policy_unmute(session: DbSession, policy_id: UUID) -> SlaPolicyOut:
    row = await unmute_sla_policy(session, policy_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="policy not found")
    return SlaPolicyOut.model_validate(row)
