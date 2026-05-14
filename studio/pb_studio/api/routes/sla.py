from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pb_studio.api.deps import DbSession, SettingsDep, verify_admin_optional
from pb_studio.sla.detector import run_sla_detection_cycle
from pb_studio.sla.schemas import SlaDetectResponse, SlaIncidentOut, SlaPolicyCreate, SlaPolicyOut
from pb_studio.sla.service import (
    acknowledge_incident,
    create_sla_policy,
    list_sla_incidents,
    list_sla_policies,
    resolve_incident,
)

router = APIRouter(prefix="/sla", tags=["sla"])


@router.get("/incidents", response_model=list[SlaIncidentOut], dependencies=[Depends(verify_admin_optional)])
async def get_sla_incidents(
    session: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SlaIncidentOut]:
    rows = await list_sla_incidents(session, status=status_filter, limit=limit)
    return [SlaIncidentOut.model_validate(r) for r in rows]


@router.post("/detect", response_model=SlaDetectResponse, dependencies=[Depends(verify_admin_optional)])
async def post_sla_detect(session: DbSession, settings: SettingsDep) -> SlaDetectResponse:
    raw = await run_sla_detection_cycle(session, settings)
    return SlaDetectResponse.model_validate(raw)


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
    )
    return SlaPolicyOut.model_validate(row)
