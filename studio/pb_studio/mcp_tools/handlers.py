from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.assistant_rules import service as assistant_rules_service
from pb_studio.assistant_rules.constants import AssistantRuleScope
from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.knowledge import service as kb_service
from pb_studio.nl.executor import (
    _digest_all_chats,
    _diagnostics_text,
    _kb_search_text,
    _list_chats_text,
    _list_projects_text,
    _project_digest_text,
    _runtime_config_query_text,
)
from pb_studio.nl.models import StudioMemoryItem, StudioPlaybook
from pb_studio.projects.service import get_project_by_slug
from pb_studio.sla.constants import SlaIncidentStatus
from pb_studio.sla.service import list_sla_incidents

_ID_TAIL_RE = re.compile(r"\s*\(id=[^)]+\)\s*$")


async def _with_session(fn: Any) -> Any:
    settings = get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        out = await fn(session, settings)
        await session.commit()
    return out


def _strip_project_ids(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        lines.append(_ID_TAIL_RE.sub("", line).rstrip())
    return "\n".join(lines)


async def studio_list_chats(include_debug: bool = False) -> str:  # noqa: ARG001
    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        return await _list_chats_text(session)

    return await _with_session(inner)


async def studio_get_report(period: str = "today", include_debug: bool = False) -> str:
    async def inner(session: AsyncSession, settings: Settings) -> str:
        p = (period or "today").strip().lower()
        if p not in ("today", "yesterday", "last_7_days", "this_week"):
            p = "today"
        if include_debug:
            s2 = settings.model_copy(update={"studio_nl_digest_debug": True})
            return await _digest_all_chats(session, s2, p)
        return await _digest_all_chats(session, settings, p)

    return await _with_session(inner)


async def studio_list_open_sla(include_debug: bool = False) -> str:
    async def inner(session: AsyncSession, settings: Settings) -> str:
        if not settings.studio_sla_enabled:
            return "SLA в Studio выключен (STUDIO_SLA_ENABLED=false)."
        rows = await list_sla_incidents(session, status=SlaIncidentStatus.OPEN, limit=50)
        if not rows:
            return "Открытых SLA-инцидентов нет."
        lines = [f"Открытые инциденты SLA: {len(rows)}"]
        for idx, inc in enumerate(rows[:20], start=1):
            if include_debug:
                lines.append(f"- #{idx} chat_id={inc.chat_id} severity={inc.severity} due={inc.due_at}")
            else:
                lines.append(f"- #{idx} severity={inc.severity} due={inc.due_at}")
        if len(rows) > 20:
            lines.append(f"... и ещё {len(rows) - 20}")
        return "\n".join(lines)

    return await _with_session(inner)


async def studio_list_projects(include_debug: bool = False) -> str:
    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        raw = await _list_projects_text(session)
        if include_debug:
            return raw
        return _strip_project_ids(raw)

    return await _with_session(inner)


async def studio_get_project_digest(
    project_name_guess: str,
    period: str = "today",
    include_debug: bool = False,
) -> str:
    async def inner(session: AsyncSession, settings: Settings) -> str:
        del include_debug
        p = (period or "today").strip().lower()
        if p not in ("today", "yesterday"):
            p = "today"
        return await _project_digest_text(session, settings, {"project_name_guess": project_name_guess, "period": p})

    return await _with_session(inner)


async def studio_search_kb(query: str, include_debug: bool = False) -> str:
    async def inner(session: AsyncSession, settings: Settings) -> str:
        del include_debug
        return await _kb_search_text(session, settings, (query or "").strip())

    return await _with_session(inner)


async def studio_get_kb_sources(limit: int = 30, include_debug: bool = False) -> str:
    lim = max(1, min(int(limit or 30), 200))

    async def inner(session: AsyncSession, settings: Settings) -> str:
        if not settings.studio_kb_enabled:
            return "KB выключена (STUDIO_KB_ENABLED=false)."
        docs = await kb_service.list_documents(session, project_id=None, status=None, limit=lim)
        if not docs:
            return "Документов KB нет."
        lines = [f"Документы KB (до {lim}):"]
        for d in docs:
            if include_debug:
                lines.append(f"- {d.title} | id={d.id} | status={d.status}")
            else:
                lines.append(f"- {d.title} | status={d.status}")
        return "\n".join(lines)

    return await _with_session(inner)


async def studio_save_behavior_rule(
    rule_text: str,
    scope: str = "global",
    project_slug: str | None = None,
    studio_chat_id: str | None = None,
) -> str:
    text = (rule_text or "").strip()
    if not text:
        return "rule_text пустой."
    sc = (scope or "global").strip().lower()

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        if sc == AssistantRuleScope.GLOBAL:
            await assistant_rules_service.create_rule(
                session,
                scope=AssistantRuleScope.GLOBAL,
                rule_text=text[:8000],
                source="mcp",
            )
            return "Правило сохранено (global)."
        if sc == AssistantRuleScope.PROJECT:
            slug = (project_slug or "").strip()
            if not slug:
                return "Для scope=project укажите project_slug."
            try:
                proj = await get_project_by_slug(session, slug)
            except ValueError:
                proj = None
            if proj is None:
                return "Проект не найден по slug."
            await assistant_rules_service.create_rule(
                session,
                scope=AssistantRuleScope.PROJECT,
                rule_text=text[:8000],
                project_id=proj.id,
                source="mcp",
            )
            return f"Правило сохранено для проекта {proj.slug}."
        if sc == AssistantRuleScope.CHAT:
            raw = (studio_chat_id or "").strip()
            if not raw:
                return "Для scope=chat укажите studio_chat_id (UUID чата в Studio)."
            try:
                cid = UUID(raw)
            except ValueError:
                return "studio_chat_id должен быть UUID."
            await assistant_rules_service.create_rule(
                session,
                scope=AssistantRuleScope.CHAT,
                rule_text=text[:8000],
                chat_id=cid,
                source="mcp",
            )
            return "Правило сохранено для чата (Studio chat UUID)."
        return "scope должен быть global | project | chat."

    return await _with_session(inner)


async def studio_save_memory_item(
    text: str,
    scope_type: str = "global",
    project_slug: str | None = None,
) -> str:
    body = (text or "").strip()
    if not body:
        return "text пустой."
    st = (scope_type or "global").strip().lower()

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        scope_id: UUID | None = None
        if st == "global":
            st_eff = "global"
        elif st == "project":
            slug = (project_slug or "").strip()
            if not slug:
                return "Для scope_type=project укажите project_slug."
            try:
                proj = await get_project_by_slug(session, slug)
            except ValueError:
                proj = None
            if proj is None:
                return "Проект не найден."
            st_eff = "project"
            scope_id = proj.id
        else:
            return "scope_type поддерживается: global | project."
        session.add(
            StudioMemoryItem(
                scope_type=st_eff,
                scope_id=scope_id,
                item_type="fact",
                text=body[:8000],
                source_message_id=None,
                source_update_id=None,
                created_by_telegram_user_id=None,
                status="active",
                confidence=None,
                metadata_json={"source": "mcp"},
            )
        )
        return "Запись studio_memory_items создана (active)."

    return await _with_session(inner)


async def studio_create_playbook_draft(title: str, description: str = "") -> str:
    t = (title or "").strip() or "Playbook"
    d = (description or "").strip()

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        pb = StudioPlaybook(
            title=t[:512],
            description=d[:8000],
            scope_type="global",
            scope_id=None,
            trigger_examples_json=[],
            steps_json=[],
            status="draft",
            created_by_telegram_user_id=None,
            source_message_id=None,
            metadata_json={"source": "mcp"},
        )
        session.add(pb)
        await session.flush()
        return f"Черновик playbook создан (draft), id={str(pb.id)[:8]}…"

    return await _with_session(inner)


async def studio_runtime_status(include_debug: bool = False) -> str:
    settings = get_settings()
    lines = [_diagnostics_text(settings)]
    lines.append(_runtime_config_query_text(settings))
    lines.append(f"STUDIO_ENV={settings.studio_env}")
    if include_debug:
        lines.append("include_debug=true — расширенный вывод ограничен; секреты не выводятся.")
    return "\n".join(lines)
