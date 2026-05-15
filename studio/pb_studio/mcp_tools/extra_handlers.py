"""MCP handlers — Phase MVP v1.

Tools для роле-aware поведения, smart-отчётов, проектов, правил и сообщений.
Каждая функция возвращает текст для ассистента Memoh; БД-сессия открывается
через единый `_with_session` (commit на выходе).

Источники истины — существующие сервисы Studio:
- pb_studio.control_group.service
- pb_studio.projects.service
- pb_studio.assistant_rules.service
- pb_studio.event_mirror.models (StudioChat, StudioMessage)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.assistant_rules import service as assistant_rules_service
from pb_studio.assistant_rules.constants import AssistantRuleScope
from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import (
    set_chat_role,
    set_control_group_by_telegram_id,
)
from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.event_mirror.models import StudioChat, StudioMessage
from pb_studio.knowledge.embeddings import redact_embedding_error
from pb_studio.projects.models import StudioProject, StudioProjectChat
from pb_studio.projects.service import (
    bind_chat_to_project as _bind_chat_to_project,
    create_project as _create_project,
    get_project_by_slug,
)


_PERIOD_TODAY = "today"
_PERIOD_YESTERDAY = "yesterday"
_PERIOD_WEEK_ALIASES = {"week", "7d", "last_7_days", "this_week"}


async def _with_session(fn: Callable[[AsyncSession, Settings], Awaitable[Any]]) -> Any:
    settings = get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        out = await fn(session, settings)
        await session.commit()
    return out


async def _resolve_studio_chat(session: AsyncSession, tg_chat_id: int) -> StudioChat | None:
    return await session.scalar(
        select(StudioChat).where(StudioChat.telegram_chat_id == int(tg_chat_id))
    )


async def _resolve_chat_by_guess(session: AsyncSession, guess: str) -> StudioChat | None:
    """Поддерживает telegram_chat_id (число) и подстроку title (case-insensitive)."""
    g = (guess or "").strip()
    if not g:
        return None
    try:
        tid = int(g)
        chat = await session.scalar(select(StudioChat).where(StudioChat.telegram_chat_id == tid))
        if chat is not None:
            return chat
    except ValueError:
        pass
    rows = list(
        (
            await session.scalars(
                select(StudioChat)
                .where(func.lower(StudioChat.title).contains(g.lower()))
                .limit(5)
            )
        ).all()
    )
    return rows[0] if len(rows) == 1 else None


def _period_bounds(period: str) -> tuple[datetime, datetime, str]:
    """Возвращает (от, до, нормализованный_лейбл) в UTC."""
    now = datetime.now(timezone.utc)
    p = (period or _PERIOD_TODAY).strip().lower()
    if p == _PERIOD_YESTERDAY:
        day = (now - timedelta(days=1)).date()
        p0 = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        return p0, p0 + timedelta(days=1), _PERIOD_YESTERDAY
    if p in _PERIOD_WEEK_ALIASES:
        return now - timedelta(days=7), now, "week"
    day = now.date()
    p0 = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    return p0, p0 + timedelta(days=1), _PERIOD_TODAY


def _can_respond_to_user(chat_role: str, from_user_in_acl: bool) -> bool:
    """K1 source-aware: service_chat — никогда; client_chat — только если автор в ACL."""
    role = (chat_role or "").lower()
    if role == ChatRole.SERVICE_CHAT.value:
        return False
    if role == ChatRole.CLIENT_CHAT.value:
        return bool(from_user_in_acl)
    return True


# ===== studio_get_chat_context =====


async def studio_get_chat_context(
    telegram_chat_id: int,
    from_user_id: int | None = None,
) -> str:
    """Контекст чата для Memoh: роль, проект, активные правила, флаг can_respond_to_user.

    Memoh обязан звать этот tool ПЕРЕД ответом в любом чате (кроме личных DM/контрольной).
    """

    async def inner(session: AsyncSession, settings: Settings) -> str:
        chat = await _resolve_studio_chat(session, int(telegram_chat_id))
        if chat is None:
            return (
                "chat_unknown=true\n"
                "Этот чат ещё не появлялся в Studio (зеркало не получало update). "
                "По умолчанию веди себя как в internal_chat."
            )

        proj_link = await session.scalar(
            select(StudioProjectChat)
            .where(
                StudioProjectChat.chat_id == chat.id,
                StudioProjectChat.is_active.is_(True),
            )
            .limit(1)
        )
        proj_row = (
            await session.get(StudioProject, proj_link.project_id) if proj_link else None
        )
        project_id = proj_row.id if proj_row else None

        acl_ids = settings.studio_control_commands_allowed_user_ids_set
        if not acl_ids:
            from_in_acl = True
        elif from_user_id is None:
            from_in_acl = False
        else:
            from_in_acl = int(from_user_id) in acl_ids
        can_respond = _can_respond_to_user(chat.chat_role, from_in_acl)

        rules = await assistant_rules_service.list_active_rules_for_kb_rag(
            session, project_id=project_id, chat_id=chat.id
        )

        lines: list[str] = [
            f"role={chat.chat_role}",
            f"title={chat.title or ''}",
            f"can_respond_to_user={'yes' if can_respond else 'no'}",
        ]
        if proj_row is not None:
            lines.append(f"project_slug={proj_row.slug}")
            lines.append(f"project_name={proj_row.name}")
        else:
            lines.append("project=none")
        if rules:
            lines.append(f"active_rules ({len(rules)}):")
            for idx, r in enumerate(rules[:30], start=1):
                lines.append(f"  {idx}. [{r.scope}] {r.rule_text}")
        else:
            lines.append("active_rules: пусто")
        if chat.chat_role == ChatRole.CLIENT_CHAT.value and not can_respond:
            lines.append(
                "ВАЖНО: client_chat. По умолчанию НЕ отвечай клиенту. "
                "Отвечай только менеджерам студии из ACL (по mention/reply)."
            )
        if chat.chat_role == ChatRole.SERVICE_CHAT.value:
            lines.append("ВАЖНО: service_chat. Никаких ответов в этот чат.")
        return "\n".join(lines)[:3500]

    return await _with_session(inner)


# ===== studio_smart_chat_report =====


async def studio_smart_chat_report(
    chat_id_or_name: str,
    period: str = "today",
    max_messages: int = 200,
) -> str:
    """LLM-отчёт «по смыслу чата». Формат выбирает LLM по содержимому
    (задачи, лиды, согласования, обзор)."""

    needle = (chat_id_or_name or "").strip()
    if not needle:
        return "Укажите имя чата или telegram_chat_id."
    max_msgs = max(10, min(int(max_messages or 200), 500))

    async def inner(session: AsyncSession, settings: Settings) -> str:
        chat = await _resolve_chat_by_guess(session, needle)
        if chat is None:
            return f"Чат '{needle}' не найден или название неоднозначно."

        p0, p1, p_label = _period_bounds(period)
        msgs = list(
            (
                await session.scalars(
                    select(StudioMessage)
                    .where(
                        StudioMessage.chat_id == chat.id,
                        StudioMessage.date >= p0,
                        StudioMessage.date < p1,
                    )
                    .order_by(StudioMessage.date.asc())
                    .limit(max_msgs)
                )
            ).all()
        )
        if not msgs:
            return (
                f"В чате '{chat.title or chat.telegram_chat_id}' за период "
                f"{p_label} сообщений не было."
            )

        transcript_lines: list[str] = []
        for m in msgs:
            txt = ((m.text or m.caption) or "").strip()
            if not txt:
                continue
            transcript_lines.append(f"[{m.date.strftime('%Y-%m-%d %H:%M')}] {txt[:500]}")
        if not transcript_lines:
            return (
                f"В чате '{chat.title or chat.telegram_chat_id}' за {p_label} "
                "только медиа без текста."
            )

        if not (settings.studio_kb_chat_api_base_url or "").strip() or not (
            settings.studio_kb_chat_api_key or ""
        ).strip():
            return (
                "LLM-отчёт недоступен: STUDIO_KB_CHAT_API_BASE_URL/KEY не настроены. "
                f"Сырых сообщений за период {p_label}: {len(msgs)}."
            )
        try:
            return await _smart_report_chat(
                settings,
                chat_title=(chat.title or str(chat.telegram_chat_id)),
                period_label=p_label,
                transcript="\n".join(transcript_lines),
            )
        except Exception as exc:  # noqa: BLE001
            return f"LLM-отчёт упал: {type(exc).__name__}: {str(exc)[:300]}"

    return await _with_session(inner)


async def _smart_report_chat(
    settings: Settings,
    *,
    chat_title: str,
    period_label: str,
    transcript: str,
) -> str:
    base = (settings.studio_kb_chat_api_base_url or "").strip().rstrip("/")
    key = (settings.studio_kb_chat_api_key or "").strip()
    model = (settings.studio_kb_chat_model or "").strip()
    if not (base and key and model):
        raise RuntimeError("STUDIO_KB_CHAT_API_BASE_URL/KEY/MODEL must be set")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    system = (
        "Ты — операционный ассистент веб-студии. Тебе дан фрагмент Telegram-чата "
        "за период. Сделай КРАТКИЙ полезный отчёт, сам определив формат по содержимому: "
        "• если есть задачи — список задач (что, кто, статус); "
        "• если лиды/заявки — конверсии и важные касания; "
        "• если согласования — открытые вопросы и принятые решения; "
        "• иначе — короткое резюме тем и решений. "
        "Не показывай служебные id/timestamp без надобности. Пиши по-русски, "
        "не длиннее 1500 символов."
    )
    user = f"Чат: {chat_title}\nПериод: {period_label}\n\nСообщения:\n{transcript}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    timeout_s = max(int(settings.studio_kb_chat_timeout_ms or 20000) / 1000.0, 5.0)
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        body = redact_embedding_error(resp.text[:1500], key)
        raise RuntimeError(f"chat HTTP {resp.status_code}: {body[:300]}")
    data = resp.json()
    content = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    ).strip()
    if not content:
        raise RuntimeError("empty completion")
    return content[:3500]


# ===== studio_assign_chat_role =====


async def studio_assign_chat_role(telegram_chat_id: int, role: str) -> str:
    role_norm = (role or "").strip().lower()
    allowed = {m.value for m in ChatRole} - {ChatRole.CONTROL_GROUP.value}
    if role_norm not in allowed:
        return (
            f"Недопустимая роль: {role!r}. "
            "Допустимо: client_chat | project_chat | internal_chat | service_chat | unknown. "
            "Контрольную группу назначай через studio_set_control_group."
        )

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        chat = await _resolve_studio_chat(session, int(telegram_chat_id))
        if chat is None:
            return (
                f"Чат telegram_chat_id={telegram_chat_id} ещё не виден Studio. "
                "Дождитесь первого сообщения от бота в этом чате."
            )
        try:
            await set_chat_role(session, studio_chat_id=chat.id, role=role_norm)
        except ValueError as exc:
            return f"Ошибка: {exc}"
        return f"Роль чата '{chat.title or chat.telegram_chat_id}' установлена: {role_norm}."

    return await _with_session(inner)


# ===== studio_set_control_group =====


async def studio_set_control_group(telegram_chat_id: int) -> str:
    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        try:
            cg = await set_control_group_by_telegram_id(session, int(telegram_chat_id))
        except ValueError as exc:
            return f"Ошибка: {exc}"
        chat = await session.get(StudioChat, cg.chat_id)
        title = chat.title if chat and chat.title else str(telegram_chat_id)
        return f"Управляющая группа установлена: '{title}'."

    return await _with_session(inner)


# ===== studio_get_active_rules =====


async def studio_get_active_rules(scope: str = "global", scope_id: str | None = None) -> str:
    sc = (scope or "global").strip().lower()
    if sc not in (
        AssistantRuleScope.GLOBAL,
        AssistantRuleScope.PROJECT,
        AssistantRuleScope.CHAT,
    ):
        return "scope должен быть global | project | chat."

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        project_id: UUID | None = None
        chat_id: UUID | None = None
        if sc == AssistantRuleScope.PROJECT:
            if not scope_id:
                return "Для scope=project укажите scope_id (project slug или UUID)."
            try:
                project_id = UUID(scope_id)
            except ValueError:
                proj = await get_project_by_slug(session, scope_id)
                if proj is None:
                    return "Проект не найден."
                project_id = proj.id
        elif sc == AssistantRuleScope.CHAT:
            if not scope_id:
                return "Для scope=chat укажите scope_id (studio UUID или telegram_chat_id)."
            try:
                chat_id = UUID(scope_id)
            except ValueError:
                try:
                    tid = int(scope_id)
                except ValueError:
                    return "scope_id должен быть UUID или telegram_chat_id (число)."
                chat = await _resolve_studio_chat(session, tid)
                if chat is None:
                    return "Чат не найден."
                chat_id = chat.id

        rules = await assistant_rules_service.list_active_rules_for_kb_rag(
            session, project_id=project_id, chat_id=chat_id
        )
        if not rules:
            return f"Активных правил нет (scope={sc})."
        lines = [f"Активные правила (scope={sc}, всего {len(rules)}):"]
        for idx, r in enumerate(rules, start=1):
            lines.append(f"{idx}. [{r.scope}] {r.rule_text}")
        return "\n".join(lines)[:3500]

    return await _with_session(inner)


# ===== studio_create_project =====


_SLUG_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _autogen_slug(name: str) -> str:
    s = (name or "").strip().lower()
    s = "".join(_SLUG_TRANSLIT.get(ch, ch) for ch in s)
    s = re.sub(r"[^a-z0-9_\s-]+", "", s)
    s = re.sub(r"\s+", "-", s).strip("-_")
    return (s or "project")[:50]


async def studio_create_project(name: str, slug: str | None = None) -> str:
    n = (name or "").strip()
    if not n:
        return "name пустой."
    effective_slug = (slug or "").strip() or _autogen_slug(n)

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        try:
            row = await _create_project(session, slug=effective_slug, name=n)
        except ValueError as exc:
            return f"Ошибка: {exc}"
        return f"Проект создан: slug={row.slug}, name={row.name}."

    return await _with_session(inner)


# ===== studio_bind_chat_to_project =====


async def studio_bind_chat_to_project(
    telegram_chat_id: int,
    project_slug: str,
    role_in_project: str = "secondary",
) -> str:
    slug = (project_slug or "").strip()
    role = (role_in_project or "secondary").strip().lower()

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        chat = await _resolve_studio_chat(session, int(telegram_chat_id))
        if chat is None:
            return f"Чат telegram_chat_id={telegram_chat_id} ещё не виден Studio."
        proj = await get_project_by_slug(session, slug)
        if proj is None:
            return f"Проект slug={slug!r} не найден."
        try:
            _, outcome = await _bind_chat_to_project(
                session, project_id=proj.id, chat_id=chat.id, role_in_project=role
            )
        except ValueError as exc:
            return f"Ошибка: {exc}"
        return (
            f"Чат '{chat.title or chat.telegram_chat_id}' привязан к проекту "
            f"'{proj.slug}' ({outcome}). Роль чата: project_chat."
        )

    return await _with_session(inner)


# ===== studio_disable_rule =====


async def studio_disable_rule(rule_id: str, reason: str | None = None) -> str:
    raw = (rule_id or "").strip()
    if not raw:
        return "rule_id пустой."
    try:
        rid = UUID(raw)
    except ValueError:
        return "rule_id должен быть UUID."

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        row = await assistant_rules_service.disable_rule(session, rid, reason=reason)
        if row is None:
            return "Правило не найдено."
        return f"Правило {rid} отключено."

    return await _with_session(inner)


# ===== studio_get_recent_messages =====


async def studio_get_recent_messages(chat_id_or_name: str, limit: int = 30) -> str:
    needle = (chat_id_or_name or "").strip()
    if not needle:
        return "Укажите имя чата или telegram_chat_id."
    lim = max(1, min(int(limit or 30), 200))

    async def inner(session: AsyncSession, settings: Settings) -> str:
        del settings
        chat = await _resolve_chat_by_guess(session, needle)
        if chat is None:
            return f"Чат '{needle}' не найден."
        msgs = list(
            (
                await session.scalars(
                    select(StudioMessage)
                    .where(StudioMessage.chat_id == chat.id)
                    .order_by(StudioMessage.date.desc())
                    .limit(lim)
                )
            ).all()
        )
        if not msgs:
            return f"В чате '{chat.title or chat.telegram_chat_id}' нет сообщений."
        msgs.reverse()
        lines = [
            f"Последние {len(msgs)} сообщений чата "
            f"'{chat.title or chat.telegram_chat_id}':"
        ]
        for m in msgs:
            txt = ((m.text or m.caption) or "").strip()[:300]
            if not txt:
                continue
            lines.append(f"[{m.date.strftime('%Y-%m-%d %H:%M')}] {txt}")
        return "\n".join(lines)[:3500]

    return await _with_session(inner)
