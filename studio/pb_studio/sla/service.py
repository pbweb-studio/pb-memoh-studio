from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.service import _audit
from pb_studio.control_group.telegram_outbound import telegram_send_message
from pb_studio.core.config import Settings
from pb_studio.sla.constants import SlaIncidentStatus
from pb_studio.sla.models import StudioSlaIncident, StudioSlaNotificationEvent, StudioSlaPolicy
from pb_studio.sla.notifications import (
    list_notification_events as _sla_list_notification_events,
    manual_notify_incident as _sla_manual_notify_incident,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_sla_policy(session: AsyncSession, policy_id: UUID) -> StudioSlaPolicy | None:
    return await session.get(StudioSlaPolicy, policy_id)


async def list_sla_incidents(
    session: AsyncSession,
    *,
    status: str | None = None,
    severity: str | None = None,
    chat_id: UUID | None = None,
    limit: int = 100,
) -> list[StudioSlaIncident]:
    lim = min(max(limit, 1), 500)
    stmt = select(StudioSlaIncident)
    if status:
        stmt = stmt.where(StudioSlaIncident.status == status)
    if severity:
        stmt = stmt.where(StudioSlaIncident.severity == severity)
    if chat_id is not None:
        stmt = stmt.where(StudioSlaIncident.chat_id == chat_id)
    stmt = stmt.order_by(StudioSlaIncident.created_at.desc()).limit(lim)
    return list((await session.scalars(stmt)).all())


async def list_sla_notification_events(
    session: AsyncSession,
    *,
    incident_id: UUID | None = None,
    limit: int = 100,
) -> list[StudioSlaNotificationEvent]:
    return await _sla_list_notification_events(session, incident_id=incident_id, limit=limit)


async def sla_manual_notify(
    session: AsyncSession,
    settings: Settings,
    incident_id: UUID,
) -> dict[str, Any]:
    return await _sla_manual_notify_incident(
        session, settings, incident_id, telegram_send_message, now=utcnow()
    )


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
    policy_tz: str | None = None,
    working_days_json: list[int] | None = None,
    working_hours_start: str | None = None,
    working_hours_end: str | None = None,
    holidays_json: list[str] | None = None,
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
        policy_tz=(policy_tz or "UTC").strip() or "UTC",
        working_days_json=working_days_json,
        working_hours_start=working_hours_start,
        working_hours_end=working_hours_end,
        holidays_json=holidays_json,
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


async def patch_sla_policy_fields(
    session: AsyncSession,
    policy_id: UUID,
    updates: dict[str, Any],
) -> StudioSlaPolicy | None:
    row = await session.get(StudioSlaPolicy, policy_id)
    if row is None:
        return None
    if "first_response_minutes" in updates:
        v = updates["first_response_minutes"]
        if v is not None:
            row.first_response_minutes = max(1, int(v))
    if "followup_minutes" in updates:
        row.followup_minutes = updates["followup_minutes"]
    if "is_active" in updates:
        row.is_active = bool(updates["is_active"])
    if "policy_tz" in updates and updates["policy_tz"] is not None:
        row.policy_tz = str(updates["policy_tz"]).strip() or "UTC"
    if "working_days_json" in updates:
        row.working_days_json = updates["working_days_json"]
    if "working_hours_start" in updates:
        row.working_hours_start = updates["working_hours_start"]
    if "working_hours_end" in updates:
        row.working_hours_end = updates["working_hours_end"]
    if "holidays_json" in updates:
        row.holidays_json = updates["holidays_json"]
    row.updated_at = utcnow()
    await _audit(
        session,
        action="sla.policy_patched",
        entity_type="studio_sla_policy",
        entity_id=str(row.id),
        payload={k: v for k, v in updates.items() if v is not None or k.endswith("_json")},
    )
    return row


async def mute_sla_policy(
    session: AsyncSession,
    policy_id: UUID,
    *,
    muted_until: datetime | None,
    mute_reason: str | None,
) -> StudioSlaPolicy | None:
    row = await session.get(StudioSlaPolicy, policy_id)
    if row is None:
        return None
    row.is_muted = True
    row.muted_until = muted_until
    row.mute_reason = mute_reason
    row.updated_at = utcnow()
    await _audit(
        session,
        action="sla.policy_muted",
        entity_type="studio_sla_policy",
        entity_id=str(row.id),
        payload={"muted_until": muted_until.isoformat() if muted_until is not None else None},
    )
    return row


async def unmute_sla_policy(session: AsyncSession, policy_id: UUID) -> StudioSlaPolicy | None:
    row = await session.get(StudioSlaPolicy, policy_id)
    if row is None:
        return None
    row.is_muted = False
    row.muted_until = None
    row.mute_reason = None
    row.updated_at = utcnow()
    await _audit(
        session,
        action="sla.policy_unmuted",
        entity_type="studio_sla_policy",
        entity_id=str(row.id),
        payload=None,
    )
    return row


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
