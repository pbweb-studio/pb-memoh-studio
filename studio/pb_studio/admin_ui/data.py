from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.assistant_rules.models import StudioAssistantRule
from pb_studio.control_group.models import StudioControlGroup
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.history_import.models import StudioHistoryImportJob
from pb_studio.knowledge.models import StudioKnowledgeDocument, StudioKnowledgeDocumentVersion
from pb_studio.projects.constants import ProjectStatus
from pb_studio.projects.models import StudioProject, StudioProjectChat
from pb_studio.sla.models import StudioSlaIncident
from pb_studio.summaries.models import StudioChatSummary


@dataclass(frozen=True)
class DashboardCounts:
    chats: int
    messages: int
    projects: int
    knowledge_documents: int
    assistant_rules: int
    history_import_jobs: int
    summaries: int
    sla_incidents: int


async def fetch_dashboard_counts(session: AsyncSession) -> DashboardCounts:
    chats = int(await session.scalar(select(func.count()).select_from(StudioChat)) or 0)
    messages = int(await session.scalar(select(func.count()).select_from(StudioMessage)) or 0)
    projects = int(await session.scalar(select(func.count()).select_from(StudioProject)) or 0)
    kb = int(await session.scalar(select(func.count()).select_from(StudioKnowledgeDocument)) or 0)
    rules = int(await session.scalar(select(func.count()).select_from(StudioAssistantRule)) or 0)
    jobs = int(await session.scalar(select(func.count()).select_from(StudioHistoryImportJob)) or 0)
    sums = int(await session.scalar(select(func.count()).select_from(StudioChatSummary)) or 0)
    sla = int(await session.scalar(select(func.count()).select_from(StudioSlaIncident)) or 0)
    return DashboardCounts(
        chats=chats,
        messages=messages,
        projects=projects,
        knowledge_documents=kb,
        assistant_rules=rules,
        history_import_jobs=jobs,
        summaries=sums,
        sla_incidents=sla,
    )


async def list_chats(session: AsyncSession, *, limit: int = 50) -> list[StudioChat]:
    lim = min(max(limit, 1), 200)
    q = select(StudioChat).order_by(StudioChat.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


def _chat_admin_conditions(*, role: str | None, q: str | None) -> list:
    parts: list = []
    if role and str(role).strip():
        parts.append(StudioChat.chat_role == str(role).strip())
    if q and str(q).strip():
        raw = str(q).strip()
        term = f"%{raw}%"
        try:
            tid = int(raw)
            parts.append(or_(StudioChat.title.ilike(term), StudioChat.telegram_chat_id == tid))
        except ValueError:
            parts.append(StudioChat.title.ilike(term))
    return parts


async def count_chats_admin(session: AsyncSession, *, role: str | None, q: str | None) -> int:
    stmt = select(func.count()).select_from(StudioChat)
    conds = _chat_admin_conditions(role=role, q=q)
    if conds:
        stmt = stmt.where(and_(*conds))
    return int(await session.scalar(stmt) or 0)


async def list_chats_admin(
    session: AsyncSession, *, role: str | None, q: str | None, limit: int, offset: int
) -> list[StudioChat]:
    stmt = select(StudioChat).order_by(StudioChat.updated_at.desc())
    conds = _chat_admin_conditions(role=role, q=q)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def fetch_control_group_view(session: AsyncSession) -> dict[str, Any] | None:
    res = await session.execute(
        select(StudioControlGroup, StudioChat)
        .join(StudioChat, StudioChat.id == StudioControlGroup.chat_id)
        .where(StudioControlGroup.is_active.is_(True))
        .limit(1)
    )
    row = res.first()
    if not row:
        return None
    cg, chat = row[0], row[1]
    return {"control_group": cg, "chat": chat}


async def active_control_group_studio_chat_id(session: AsyncSession) -> UUID | None:
    v = await fetch_control_group_view(session)
    return v["chat"].id if v else None


async def list_group_supergroup_chats_for_control_group(session: AsyncSession, *, limit: int = 500) -> list[StudioChat]:
    """Telegram group/supergroup only (excludes private), for control group assignment UI."""
    lim = min(max(limit, 1), 1000)
    stmt = (
        select(StudioChat)
        .where(or_(func.lower(StudioChat.chat_type) == "group", func.lower(StudioChat.chat_type) == "supergroup"))
        .order_by(StudioChat.title.asc().nullslast(), StudioChat.telegram_chat_id.asc())
        .limit(lim)
    )
    return list((await session.scalars(stmt)).all())


async def list_summaries(session: AsyncSession, *, limit: int = 50) -> list[StudioChatSummary]:
    lim = min(max(limit, 1), 200)
    q = select(StudioChatSummary).order_by(StudioChatSummary.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


def _summary_admin_conditions(*, status: str | None, delivery_status: str | None) -> list:
    parts: list = []
    if status and str(status).strip():
        parts.append(StudioChatSummary.status == str(status).strip())
    if delivery_status and str(delivery_status).strip():
        parts.append(StudioChatSummary.delivery_status == str(delivery_status).strip())
    return parts


async def count_summaries_admin(session: AsyncSession, *, status: str | None, delivery_status: str | None) -> int:
    stmt = select(func.count()).select_from(StudioChatSummary)
    conds = _summary_admin_conditions(status=status, delivery_status=delivery_status)
    if conds:
        stmt = stmt.where(and_(*conds))
    return int(await session.scalar(stmt) or 0)


async def list_summaries_admin(
    session: AsyncSession,
    *,
    status: str | None,
    delivery_status: str | None,
    limit: int,
    offset: int,
) -> list[StudioChatSummary]:
    stmt = select(StudioChatSummary).order_by(StudioChatSummary.created_at.desc())
    conds = _summary_admin_conditions(status=status, delivery_status=delivery_status)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def list_projects(session: AsyncSession, *, limit: int = 50) -> list[StudioProject]:
    lim = min(max(limit, 1), 200)
    q = select(StudioProject).order_by(StudioProject.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


def _project_admin_conditions(*, status: str | None) -> list:
    parts: list = []
    if status and str(status).strip():
        parts.append(StudioProject.status == str(status).strip())
    return parts


async def count_projects_admin(session: AsyncSession, *, status: str | None) -> int:
    stmt = select(func.count()).select_from(StudioProject)
    conds = _project_admin_conditions(status=status)
    if conds:
        stmt = stmt.where(and_(*conds))
    return int(await session.scalar(stmt) or 0)


async def list_projects_admin(
    session: AsyncSession, *, status: str | None, limit: int, offset: int
) -> list[StudioProject]:
    stmt = select(StudioProject).order_by(StudioProject.updated_at.desc())
    conds = _project_admin_conditions(status=status)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def list_projects_all_for_filter(session: AsyncSession, *, limit: int = 500) -> list[StudioProject]:
    lim = min(max(limit, 1), 1000)
    q = select(StudioProject).order_by(StudioProject.name.asc()).limit(lim)
    return list((await session.scalars(q)).all())


async def list_sla_incidents(session: AsyncSession, *, limit: int = 50) -> list[StudioSlaIncident]:
    lim = min(max(limit, 1), 200)
    q = select(StudioSlaIncident).order_by(StudioSlaIncident.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


def _sla_admin_conditions(*, status: str | None, severity: str | None) -> list:
    parts: list = []
    if status and str(status).strip():
        parts.append(StudioSlaIncident.status == str(status).strip())
    if severity and str(severity).strip():
        parts.append(StudioSlaIncident.severity == str(severity).strip())
    return parts


async def count_sla_incidents_admin(session: AsyncSession, *, status: str | None, severity: str | None) -> int:
    stmt = select(func.count()).select_from(StudioSlaIncident)
    conds = _sla_admin_conditions(status=status, severity=severity)
    if conds:
        stmt = stmt.where(and_(*conds))
    return int(await session.scalar(stmt) or 0)


async def list_sla_incidents_admin(
    session: AsyncSession, *, status: str | None, severity: str | None, limit: int, offset: int
) -> list[StudioSlaIncident]:
    stmt = select(StudioSlaIncident).order_by(StudioSlaIncident.created_at.desc())
    conds = _sla_admin_conditions(status=status, severity=severity)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def list_knowledge_documents(session: AsyncSession, *, limit: int = 50) -> list[StudioKnowledgeDocument]:
    lim = min(max(limit, 1), 200)
    q = select(StudioKnowledgeDocument).order_by(StudioKnowledgeDocument.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


def _kb_doc_admin_conditions(*, status: str | None, source_type: str | None, project_id: UUID | None) -> list:
    parts: list = []
    if status and str(status).strip():
        parts.append(StudioKnowledgeDocument.status == str(status).strip())
    if source_type and str(source_type).strip():
        parts.append(StudioKnowledgeDocument.source_type == str(source_type).strip())
    if project_id is not None:
        parts.append(StudioKnowledgeDocument.project_id == project_id)
    return parts


async def count_knowledge_documents_admin(
    session: AsyncSession,
    *,
    status: str | None,
    source_type: str | None,
    project_id: UUID | None,
) -> int:
    stmt = select(func.count()).select_from(StudioKnowledgeDocument)
    conds = _kb_doc_admin_conditions(status=status, source_type=source_type, project_id=project_id)
    if conds:
        stmt = stmt.where(and_(*conds))
    return int(await session.scalar(stmt) or 0)


async def list_knowledge_documents_admin(
    session: AsyncSession,
    *,
    status: str | None,
    source_type: str | None,
    project_id: UUID | None,
    limit: int,
    offset: int,
) -> list[StudioKnowledgeDocument]:
    stmt = select(StudioKnowledgeDocument).order_by(StudioKnowledgeDocument.updated_at.desc())
    conds = _kb_doc_admin_conditions(status=status, source_type=source_type, project_id=project_id)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def list_assistant_rules(session: AsyncSession, *, limit: int = 100) -> list[StudioAssistantRule]:
    lim = min(max(limit, 1), 200)
    q = select(StudioAssistantRule).order_by(StudioAssistantRule.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


def _rules_admin_conditions(*, status: str | None, scope: str | None) -> list:
    parts: list = []
    if status and str(status).strip():
        parts.append(StudioAssistantRule.status == str(status).strip())
    if scope and str(scope).strip():
        parts.append(StudioAssistantRule.scope == str(scope).strip().lower())
    return parts


async def count_assistant_rules_admin(session: AsyncSession, *, status: str | None, scope: str | None) -> int:
    stmt = select(func.count()).select_from(StudioAssistantRule)
    conds = _rules_admin_conditions(status=status, scope=scope)
    if conds:
        stmt = stmt.where(and_(*conds))
    return int(await session.scalar(stmt) or 0)


async def list_assistant_rules_admin(
    session: AsyncSession, *, status: str | None, scope: str | None, limit: int, offset: int
) -> list[StudioAssistantRule]:
    stmt = select(StudioAssistantRule).order_by(StudioAssistantRule.updated_at.desc())
    conds = _rules_admin_conditions(status=status, scope=scope)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def list_history_import_jobs(session: AsyncSession, *, limit: int = 50) -> list[StudioHistoryImportJob]:
    lim = min(max(limit, 1), 200)
    q = select(StudioHistoryImportJob).order_by(StudioHistoryImportJob.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


async def count_history_import_jobs(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(StudioHistoryImportJob)
    return int(await session.scalar(stmt) or 0)


async def list_history_import_jobs_page(
    session: AsyncSession, *, limit: int, offset: int
) -> list[StudioHistoryImportJob]:
    stmt = (
        select(StudioHistoryImportJob)
        .order_by(StudioHistoryImportJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(stmt)).all())


async def get_chat(session: AsyncSession, chat_id: UUID) -> StudioChat | None:
    return await session.get(StudioChat, chat_id)


async def list_project_links_for_chat(
    session: AsyncSession, chat_id: UUID
) -> list[tuple[StudioProject, StudioProjectChat]]:
    res = await session.execute(
        select(StudioProject, StudioProjectChat)
        .join(StudioProjectChat, StudioProjectChat.project_id == StudioProject.id)
        .where(StudioProjectChat.chat_id == chat_id, StudioProjectChat.is_active.is_(True))
    )
    return [(row[0], row[1]) for row in res.all()]


async def list_chats_for_select(session: AsyncSession, *, limit: int = 100) -> list[StudioChat]:
    lim = min(max(limit, 1), 200)
    q = select(StudioChat).order_by(StudioChat.updated_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


async def list_projects_active_for_select(session: AsyncSession, *, limit: int = 100) -> list[StudioProject]:
    lim = min(max(limit, 1), 200)
    q = (
        select(StudioProject)
        .where(StudioProject.status == ProjectStatus.ACTIVE.value)
        .order_by(StudioProject.name.asc())
        .limit(lim)
    )
    return list((await session.scalars(q)).all())


async def get_project_row(session: AsyncSession, project_id: UUID) -> StudioProject | None:
    return await session.get(StudioProject, project_id)


async def list_project_chat_links(
    session: AsyncSession, project_id: UUID, *, active_only: bool = True
) -> list[tuple[StudioProjectChat, StudioChat]]:
    q = (
        select(StudioProjectChat, StudioChat)
        .join(StudioChat, StudioChat.id == StudioProjectChat.chat_id)
        .where(StudioProjectChat.project_id == project_id)
    )
    if active_only:
        q = q.where(StudioProjectChat.is_active.is_(True))
    res = await session.execute(q)
    return [(pc, ch) for pc, ch in res.all()]


async def get_kb_document_bundle(
    session: AsyncSession, document_id: UUID
) -> tuple[StudioKnowledgeDocument | None, list[StudioKnowledgeDocumentVersion]]:
    doc = await session.get(StudioKnowledgeDocument, document_id)
    if doc is None:
        return None, []
    vers = list(
        (
            await session.scalars(
                select(StudioKnowledgeDocumentVersion)
                .where(StudioKnowledgeDocumentVersion.document_id == document_id)
                .order_by(StudioKnowledgeDocumentVersion.version_number.asc())
            )
        ).all()
    )
    return doc, vers


async def get_sla_incident(session: AsyncSession, incident_id: UUID) -> StudioSlaIncident | None:
    return await session.get(StudioSlaIncident, incident_id)


async def get_assistant_rule(session: AsyncSession, rule_id: UUID) -> StudioAssistantRule | None:
    return await session.get(StudioAssistantRule, rule_id)
