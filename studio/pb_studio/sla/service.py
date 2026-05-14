from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.service import _audit
from pb_studio.sla.constants import SlaIncidentStatus
from pb_studio.sla.models import StudioSlaIncident, StudioSlaPolicy


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def list_sla_incidents(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[StudioSlaIncident]:
    lim = min(max(limit, 1), 500)
    stmt = select(StudioSlaIncident)
    if status:
        stmt = stmt.where(StudioSlaIncident.status == status)
    stmt = stmt.order_by(StudioSlaIncident.created_at.desc()).limit(lim)
    return list((await session.scalars(stmt)).all())


async def list_sla_policies(session: AsyncSession) -> list[StudioSlaPolicy]:
    return list(
        (await session.scalars(select(StudioSlaPolicy).order_by(StudioSlaPolicy.chat_role.asc()))).all()
    )


async def create_sla_policy(
    session: AsyncSession,
    *,
    chat_role: str,
    first_response_minutes: int,
    followup_minutes: int | None,
    is_active: bool,
) -> StudioSlaPolicy:
    if is_active:
        existing = (
            await session.scalars(
                select(StudioSlaPolicy).where(
                    StudioSlaPolicy.chat_role == chat_role,
                    StudioSlaPolicy.is_active.is_(True),
                )
            )
        ).all()
        for row in existing:
            row.is_active = False
            row.updated_at = utcnow()

    pol = StudioSlaPolicy(
        chat_role=chat_role,
        first_response_minutes=max(1, int(first_response_minutes)),
        followup_minutes=followup_minutes,
        is_active=is_active,
    )
    session.add(pol)
    await session.flush()
    await _audit(
        session,
        action="sla.policy_created",
        entity_type="studio_sla_policy",
        entity_id=str(pol.id),
        payload={"chat_role": chat_role, "is_active": is_active},
    )
    return pol


async def acknowledge_incident(session: AsyncSession, incident_id: UUID) -> StudioSlaIncident | None:
    row = await session.get(StudioSlaIncident, incident_id)
    if row is None:
        return None
    if row.status == SlaIncidentStatus.OPEN.value:
        row.status = SlaIncidentStatus.ACKNOWLEDGED.value
        row.acknowledged_at = utcnow()
        row.updated_at = utcnow()
        await _audit(
            session,
            action="sla.incident_acknowledged",
            entity_type="studio_sla_incident",
            entity_id=str(row.id),
            payload=None,
        )
    return row


async def resolve_incident(session: AsyncSession, incident_id: UUID) -> StudioSlaIncident | None:
    row = await session.get(StudioSlaIncident, incident_id)
    if row is None:
        return None
    if row.status in (SlaIncidentStatus.OPEN.value, SlaIncidentStatus.ACKNOWLEDGED.value):
        row.status = SlaIncidentStatus.RESOLVED.value
        row.resolved_at = utcnow()
        row.updated_at = utcnow()
        base = dict(row.metadata_json or {})
        base["resolved_reason"] = base.get("resolved_reason") or "manual"
        row.metadata_json = base
        await _audit(
            session,
            action="sla.incident_resolved_manual",
            entity_type="studio_sla_incident",
            entity_id=str(row.id),
            payload=None,
        )
    return row
