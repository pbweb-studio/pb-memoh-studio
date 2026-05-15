from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_commands.constants import SUMMARY_AGG_SNIPPET_CHARS, TELEGRAM_TEXT_SAFE_MAX
from pb_studio.control_commands.service import _list_mirror_chats_excluding_control_group, _safe_truncate
from pb_studio.control_group.service import get_control_group_chat
from pb_studio.core.config import Settings
from pb_studio.knowledge.rag import ask_knowledge_base
from pb_studio.knowledge.service import search_knowledge_chunks
from pb_studio.nl.constants import LearningType
from pb_studio.nl.schemas import IntentEnum, NLRouterDecision, RouterModeEnum
from pb_studio.project_digests.constants import ProjectDigestType
from pb_studio.projects.constants import ProjectStatus
from pb_studio.projects.models import StudioProject
from pb_studio.projects.service import get_project_by_slug, list_projects
from pb_studio.sla.constants import SlaIncidentStatus
from pb_studio.sla.service import list_sla_incidents
from pb_studio.summaries.constants import SummaryType
from pb_studio.summaries.product import ensure_chat_summary_for_period, utc_today_period, utc_yesterday_period

logger = logging.getLogger(__name__)


async def _digest_all_chats(session: AsyncSession, settings: Settings, period: str) -> str:
    cg = await get_control_group_chat(session)
    if cg is None:
        return "Управляющая группа не настроена."
    if period == "yesterday":
        p0, p1 = utc_yesterday_period()
        label = "вчера"
    elif period in ("last_7_days", "this_week"):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        p1 = now
        p0 = p1 - timedelta(days=7)
        label = "7 дней"
    else:
        p0, p1 = utc_today_period()
        label = "сегодня"
    chats = await _list_mirror_chats_excluding_control_group(session, exclude_chat_id=cg.id)
    header = f"Сводки ({label}, UTC): {p0.isoformat()} — {p1.isoformat()}\nЧатов: {len(chats)}\n"
    blocks: list[str] = []
    meta = {"source": "nl_studio_digest"}
    stype = SummaryType.MANUAL if period == "last_7_days" else SummaryType.DAILY
    for ch in chats:
        block_head = f"\n---\n{ch.id} | tg={ch.telegram_chat_id} | role={ch.chat_role}\n"
        try:
            summary = await ensure_chat_summary_for_period(
                session,
                studio_chat_id=ch.id,
                summary_type=stype,
                period_start=p0,
                period_end=p1,
                settings=settings,
                metadata_json=meta,
            )
            snip = (summary.summary_text or "")[:SUMMARY_AGG_SNIPPET_CHARS]
            blocks.append(block_head + f"summary_id={summary.id} status={summary.status}\n{snip}")
        except Exception as exc:  # noqa: BLE001
            blocks.append(block_head + f"ошибка: {str(exc)[:200]}")
    return _safe_truncate(header + "".join(blocks), TELEGRAM_TEXT_SAFE_MAX)


async def _resolve_project(session: AsyncSession, guess: str | None) -> StudioProject | None:
    if not guess or not str(guess).strip():
        return None
    g = str(guess).strip()
    try:
        p = await get_project_by_slug(session, g)
        if p is not None:
            return p
    except ValueError:
        pass
    gl = g.lower()
    for row in await list_projects(session, status=ProjectStatus.ACTIVE.value, limit=200):
        if gl == row.slug.lower() or gl in (row.name or "").lower():
            return row
    return None


async def _project_digest_text(session: AsyncSession, settings: Settings, params: dict[str, Any]) -> str:
    guess = params.get("project_name_guess")
    proj = await _resolve_project(session, str(guess) if guess else "")
    if proj is None:
        return "Проект не найден. Уточните slug или название."
    period = str(params.get("period") or "today")
    if period == "yesterday":
        p0, p1 = utc_yesterday_period()
    else:
        p0, p1 = utc_today_period()
    from pb_studio.project_digests import service as pd_svc

    row = await pd_svc.get_digest_by_period(
        session,
        project_id=proj.id,
        digest_type=ProjectDigestType.DAILY.value,
        period_start=p0,
        period_end=p1,
    )
    if row is None or not (row.digest_text or "").strip():
        return f"Проект {proj.slug}: за период дайджеста нет."
    return _safe_truncate(f"Проект {proj.slug} ({proj.name})\n\n{row.digest_text}", TELEGRAM_TEXT_SAFE_MAX)


async def _risks_sla_text(session: AsyncSession, settings: Settings) -> str:
    if not settings.studio_sla_enabled:
        return "SLA в Studio выключен (STUDIO_SLA_ENABLED=false)."
    rows = await list_sla_incidents(session, status=SlaIncidentStatus.OPEN, limit=50)
    if not rows:
        return "Открытых SLA-инцидентов нет."
    lines = [f"Открытые инциденты SLA: {len(rows)}"]
    for inc in rows[:20]:
        lines.append(f"- chat_id={inc.chat_id} severity={inc.severity} due={inc.due_at}")
    if len(rows) > 20:
        lines.append(f"... и ещё {len(rows) - 20}")
    return _safe_truncate("\n".join(lines), TELEGRAM_TEXT_SAFE_MAX)


async def _list_chats_text(session: AsyncSession) -> str:
    cg = await get_control_group_chat(session)
    if cg is None:
        return "Control group не настроена."
    chats = await _list_mirror_chats_excluding_control_group(session, exclude_chat_id=cg.id)
    if not chats:
        return "Нет зеркалируемых чатов (кроме control group)."
    lines = ["Чаты Studio (кроме активной control group):", ""]
    for c in chats[:40]:
        title = (c.title or "").strip() or "-"
        lines.append(f"{c.id} | tg={c.telegram_chat_id} | role={c.chat_role} | {title}")
    if len(chats) > 40:
        lines.append(f"... и ещё {len(chats) - 40}")
    return _safe_truncate("\n".join(lines), TELEGRAM_TEXT_SAFE_MAX)


async def _list_projects_text(session: AsyncSession) -> str:
    rows = await list_projects(session, status=ProjectStatus.ACTIVE.value, limit=80)
    if not rows:
        return "Активных проектов нет."
    lines = ["Активные проекты:"]
    for p in rows:
        lines.append(f"- {p.slug} — {p.name} (id={p.id})")
    return _safe_truncate("\n".join(lines), TELEGRAM_TEXT_SAFE_MAX)


async def _kb_search_text(session: AsyncSession, settings: Settings, q: str) -> str:
    if not settings.studio_kb_enabled:
        return "KB выключена (STUDIO_KB_ENABLED=false)."
    if not settings.studio_kb_embeddings_enabled:
        return "Поиск по KB выключен (нужны STUDIO_KB_EMBEDDINGS_ENABLED)."
    hits = await search_knowledge_chunks(session, settings, query=q, project_id=None, top_k=settings.studio_kb_search_top_k)
    if not hits:
        return "По запросу ничего не найдено в базе знаний."
    parts = [f"Найдено фрагментов: {len(hits)}"]
    for h in hits[:10]:
        parts.append(f"\n[doc={h.document_id} chunk={h.chunk_id}]\n{(h.content_text or '')[:500]}")
    return _safe_truncate("\n".join(parts), TELEGRAM_TEXT_SAFE_MAX)


async def _kb_ask_text(session: AsyncSession, settings: Settings, question: str) -> str:
    if not settings.studio_kb_enabled:
        return "KB выключена (STUDIO_KB_ENABLED=false)."
    if not settings.studio_kb_rag_enabled:
        return "RAG выключен (STUDIO_KB_RAG_ENABLED=false)."
    try:
        res = await ask_knowledge_base(session, settings, question=question)
    except Exception as exc:  # noqa: BLE001
        return f"KB ask ошибка: {str(exc)[:500]}"
    tail = ""
    if res.sources:
        tail = "\n\nИсточники: " + ", ".join(f"{h.document_id}:{h.chunk_id}" for h in res.sources[:5])
    return _safe_truncate(res.answer + tail, TELEGRAM_TEXT_SAFE_MAX)


def _diagnostics_text(settings: Settings) -> str:
    parts = [
        "Studio diagnostics (без секретов):",
        f"STUDIO_NL_COMMANDS_ENABLED={settings.studio_nl_commands_enabled}",
        f"STUDIO_CONTROL_COMMANDS_ENABLED={settings.studio_control_commands_enabled}",
        f"STUDIO_KB_ENABLED={settings.studio_kb_enabled}",
        f"STUDIO_KB_RAG_ENABLED={settings.studio_kb_rag_enabled}",
        f"STUDIO_SLA_ENABLED={settings.studio_sla_enabled}",
        f"STUDIO_SUMMARY_GENERATION_ENABLED={settings.studio_summary_generation_enabled}",
        f"TELEGRAM_BOT_TOKEN set={'yes' if (settings.telegram_bot_token or '').strip() else 'no'}",
    ]
    return "\n".join(parts)


def _help_capabilities_text() -> str:
    return (
        "Можно писать обычным языком в управляющей группе (с @ботом или ответом боту, либо префикс «джарвис, …»):\n"
        "— отчёт за сегодня/вчера/неделю;\n"
        "— что горит / кто без ответа (SLA);\n"
        "— сводка по проекту;\n"
        "— списки чатов и проектов;\n"
        "— поиск и вопросы по базе знаний;\n"
        "— «запомни …», «научись …» (с подтверждением).\n"
        "Slash-команды остаются как fallback/debug."
    )


async def format_nl_reply(
    session: AsyncSession,
    settings: Settings,
    decision: NLRouterDecision,
    *,
    raw_input: str,
) -> str:
    if decision.mode == RouterModeEnum.refusal:
        return decision.clarify_question or "Отказ по политике безопасности."

    if decision.mode == RouterModeEnum.clarify:
        return decision.clarify_question or "Уточните запрос."

    if decision.mode == RouterModeEnum.casual:
        return "Я на связи. Напишите, что нужно по студии (отчёт, SLA, проект, база знаний) или используйте slash-команды."

    if decision.mode != RouterModeEnum.business_action or decision.intent is None:
        return "Пока не умею выполнить это автоматически."

    intent = decision.intent
    params = decision.parameters or {}

    if intent == IntentEnum.help_capabilities:
        return _help_capabilities_text()
    if intent == IntentEnum.diagnostics_status:
        return _diagnostics_text(settings)
    if intent == IntentEnum.list_chats:
        return await _list_chats_text(session)
    if intent == IntentEnum.list_projects:
        return await _list_projects_text(session)
    if intent == IntentEnum.open_risks_or_sla:
        return await _risks_sla_text(session, settings)
    if intent == IntentEnum.studio_digest:
        period = str(params.get("period") or "today")
        return await _digest_all_chats(session, settings, period)
    if intent == IntentEnum.project_digest:
        return await _project_digest_text(session, settings, params)
    if intent == IntentEnum.kb_search:
        return await _kb_search_text(session, settings, str(params.get("query") or raw_input))
    if intent == IntentEnum.kb_ask:
        return await _kb_ask_text(session, settings, str(params.get("question") or raw_input))

    return "Intent не реализован в MVP executor."


def learning_confirmation_message(draft: dict[str, Any]) -> str:
    lt = str(draft.get("learning_type") or "")
    if lt == LearningType.BEHAVIOR_RULE:
        return (
            "Понял как правило поведения. Сохранить глобально для всей студии?\n"
            "Ответьте: да / нет / для проекта SLUG / для этого чата."
        )
    if lt == LearningType.WORKFLOW_PLAYBOOK:
        return "Сохранить черновик playbook в Studio? Ответьте: да или нет."
    if lt == LearningType.KNOWLEDGE_NOTE:
        return "Сохранить как заметку (memory item)? Ответьте: да или нет."
    if lt == LearningType.KNOWLEDGE_DOCUMENT:
        return "Создать документ KB из текста? Ответьте: да или нет."
    return "Подтвердите действие: да или нет."
