from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from uuid import UUID

from sqlalchemy import func, select
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


async def list_summaries(session: AsyncSession, *, limit: int = 50) -> list[StudioChatSummary]:
    lim = min(max(limit, 1), 200)
    q = select(StudioChatSummary).order_by(StudioChatSummary.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


async def list_projects(session: AsyncSession, *, limit: int = 50) -> list[StudioProject]:
    lim = min(max(limit, 1), 200)
    q = select(StudioProject).order_by(StudioProject.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


async def list_sla_incidents(session: AsyncSession, *, limit: int = 50) -> list[StudioSlaIncident]:
    lim = min(max(limit, 1), 200)
    q = select(StudioSlaIncident).order_by(StudioSlaIncident.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


async def list_knowledge_documents(session: AsyncSession, *, limit: int = 50) -> list[StudioKnowledgeDocument]:
    lim = min(max(limit, 1), 200)
    q = select(StudioKnowledgeDocument).order_by(StudioKnowledgeDocument.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


async def list_assistant_rules(session: AsyncSession, *, limit: int = 100) -> list[StudioAssistantRule]:
    lim = min(max(limit, 1), 200)
    q = select(StudioAssistantRule).order_by(StudioAssistantRule.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


async def list_history_import_jobs(session: AsyncSession, *, limit: int = 50) -> list[StudioHistoryImportJob]:
    lim = min(max(limit, 1), 200)
    q = select(StudioHistoryImportJob).order_by(StudioHistoryImportJob.created_at.desc()).limit(lim)
    return list((await session.scalars(q)).all())


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
