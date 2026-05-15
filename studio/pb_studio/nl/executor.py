"""MCP report helpers.

Используется Studio MCP-handlers и Studio Admin как набор read-only утилит для
формирования текстов отчётов / поиска / диагностики. Это НЕ NL responder —
ответы в Telegram даёт Memoh; этот модуль просто отдаёт текстовые блоки,
которые Memoh может включить в свой ответ через MCP tools.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_commands.constants import SUMMARY_AGG_SNIPPET_CHARS, TELEGRAM_TEXT_SAFE_MAX
from pb_studio.control_commands.service import _list_mirror_chats_excluding_control_group, _safe_truncate
from pb_studio.control_group.service import get_control_group_chat
from pb_studio.core.config import Settings
from pb_studio.event_mirror.models import StudioChat
from pb_studio.knowledge.rag import ask_knowledge_base
from pb_studio.knowledge.service import search_knowledge_chunks
from pb_studio.project_digests.constants import ProjectDigestType
from pb_studio.projects.constants import ProjectStatus
from pb_studio.projects.models import StudioProject
from pb_studio.projects.service import get_project_by_slug, list_projects
from pb_studio.sla.constants import SlaIncidentStatus
from pb_studio.sla.service import list_sla_incidents
from pb_studio.summaries.constants import SummaryStatus, SummaryType
from pb_studio.summaries.product import ensure_chat_summary_for_period, utc_today_period, utc_yesterday_period

logger = logging.getLogger(__name__)

_UUID_LINE_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)


def _sanitize_nl_summary_snippet(text: str) -> str:
    """Убрать из фрагмента сводки техполя, если они попали из старых шаблонов/LLM."""
    if not (text or "").strip():
        return ""
    kept: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        sl = s.lower()
        if "summary_id=" in sl:
            continue
        if "tg=" in sl or "| tg=" in sl:
            continue
        if "role=" in sl or "| role=" in sl:
            continue
        if sl.startswith("---"):
            continue
        if ("status=" in sl or "статус=" in sl) and "generated" in sl:
            continue
        if _UUID_LINE_RE.search(s) and ("|" in s or "tg=" in sl or "role=" in sl):
            continue
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def _human_chat_line_for_nl(chat: StudioChat) -> str:
    """Одна строка для пользователя: без UUID/tg/role."""
    ct = (chat.chat_type or "").strip().lower()
    title = (chat.title or "").strip()
    if title and _UUID_LINE_RE.fullmatch(title.replace(" ", "")):
        title = ""
    username = (chat.username or "").strip()
    tid = int(chat.telegram_chat_id)
    is_groupish = ct in ("group", "supergroup") or tid < 0
    if is_groupish:
        if title:
            return f"группа {title}"
        if username:
            return f"группа @{username}"
        return "группа без названия"
    if ct == "private" or tid > 0:
        if title:
            return f"личка с {title}"
        if username:
            return f"личка @{username}"
        return "личка"
    if title:
        return title
    return "чат без названия"


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
    meta = {"source": "nl_studio_digest"}
    stype = SummaryType.MANUAL if period == "last_7_days" else SummaryType.DAILY

    if settings.studio_nl_digest_debug:
        header = f"Сводки ({label}, UTC): {p0.isoformat()} — {p1.isoformat()}\nЧатов: {len(chats)}\n"
        if (settings.studio_env or "").strip().lower() == "production":
            logger.warning("studio_nl_digest_debug is True in production; raw NL digest exposes IDs")
        header = "[debug]\n" + header
        blocks: list[str] = []
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

    intro = f"Кратко за период: {label} (по сводкам Studio, чатов в зеркале: {len(chats)}).\n\n"
    per_blocks: list[str] = []
    important: list[str] = []
    had_any_text = False
    for ch in chats:
        human = _human_chat_line_for_nl(ch)
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
            snip = (summary.summary_text or "").strip()
            if summary.status == SummaryStatus.FAILED:
                important.append(f"— Сводка не сформировалась: {human}.")
            elif snip:
                had_any_text = True
                body = _sanitize_nl_summary_snippet(snip[:SUMMARY_AGG_SNIPPET_CHARS])
                if not body:
                    important.append(f"— Текст сводки скрыт (технические поля): {human}.")
                else:
                    per_blocks.append(f"{human}\n{body}\n")
            else:
                important.append(f"— Пока нет текста сводки: {human}.")
        except Exception:  # noqa: BLE001
            important.append(f"— Не удалось получить сводку: {human}.")

    body_parts: list[str] = [intro]
    if per_blocks:
        body_parts.append("По чатам:\n\n")
        body_parts.append("\n".join(per_blocks))
    else:
        body_parts.append("По чатам пока мало данных (пустые сводки или их ещё не было).\n\n")

    if important:
        body_parts.append("Важное:\n")
        body_parts.extend(f"{line}\n" for line in important)
        body_parts.append("\n")

    body_parts.append("Риски / на что обратить внимание:\n")
    if not had_any_text and not important:
        body_parts.append(
            "— Данных мало: за выбранный период почти нет содержательных сводок по зеркалу.\n"
        )
    elif important:
        body_parts.append("— См. блок «Важное» выше.\n")
    else:
        body_parts.append("— Явных сбоев по сбору не видно; при необходимости проверьте SLA и логи генерации сводок.\n")

    return _safe_truncate("".join(body_parts), TELEGRAM_TEXT_SAFE_MAX)


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
    lines = ["Вижу такие чаты:", ""]
    lines.append(f"• {_human_chat_line_for_nl(cg)}")
    for c in chats[:40]:
        lines.append(f"• {_human_chat_line_for_nl(c)}")
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
        f"STUDIO_CONTROL_COMMANDS_ENABLED={settings.studio_control_commands_enabled}",
        f"STUDIO_KB_ENABLED={settings.studio_kb_enabled}",
        f"STUDIO_KB_RAG_ENABLED={settings.studio_kb_rag_enabled}",
        f"STUDIO_SLA_ENABLED={settings.studio_sla_enabled}",
        f"STUDIO_SUMMARY_GENERATION_ENABLED={settings.studio_summary_generation_enabled}",
        f"TELEGRAM_BOT_TOKEN set={'yes' if (settings.telegram_bot_token or '').strip() else 'no'}",
    ]
    return "\n".join(parts)


def _runtime_config_query_text(settings: Settings) -> str:
    return (
        "Имя текущей модели Memoh нужно смотреть в Memoh Admin → Bot / Provider settings — "
        "Studio не имеет прямого доступа к runtime Memoh."
    )
