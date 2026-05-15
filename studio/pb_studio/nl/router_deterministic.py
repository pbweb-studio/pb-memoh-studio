from __future__ import annotations

import re
from typing import Any

from pb_studio.nl.constants import LearningType
from pb_studio.nl.schemas import IntentEnum, NLRouterDecision, RouterModeEnum


def _low(s: str) -> str:
    return (s or "").strip().lower()


def _extract_project_guess(text: str) -> str | None:
    m = re.search(
        r"(?:по\s+проекту|проект)\s+([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9 _\-]{1,80})",
        text.strip(),
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


def _period_params(text_low: str) -> dict[str, Any]:
    if "вчера" in text_low or "yesterday" in text_low:
        return {"period": "yesterday"}
    if "недел" in text_low or "7 д" in text_low or "last_7" in text_low:
        return {"period": "last_7_days"}
    if "сегодня" in text_low or "today" in text_low:
        return {"period": "today"}
    return {"period": "today"}


def route_deterministic(text: str) -> NLRouterDecision:
    """Deterministic intent buckets for tests and offline."""
    raw = (text or "").strip()
    low = _low(raw)

    if any(
        x in low
        for x in (
            "удали все правила",
            "удали все",
            "почисти проект",
            "перезапиши баз",
            "drop database",
        )
    ):
        return NLRouterDecision(
            mode=RouterModeEnum.refusal,
            intent=IntentEnum.unclear,
            confidence=0.95,
            parameters={"subtype": LearningType.DANGEROUS_CHANGE},
            needs_confirmation=False,
            clarify_question="Такие операции здесь не выполняются автоматически. Обратитесь к администратору.",
        )

    if any(
        x in low
        for x in (
            "поменяй модель",
            "смени модель",
            "отключи rag",
            "выключи rag",
            "другой промпт",
            "change model",
        )
    ):
        return NLRouterDecision(
            mode=RouterModeEnum.refusal,
            intent=IntentEnum.learning_request,
            confidence=0.9,
            parameters={"learning_type": LearningType.BOT_CONFIG_REQUEST},
            needs_confirmation=False,
            clarify_question="Изменение модели/RAG/промпта делает только администратор (Memoh / Studio Admin).",
        )

    if "научись" in low or ("когда приходит" in low and "лид" in low):
        return NLRouterDecision(
            mode=RouterModeEnum.learning,
            intent=IntentEnum.learning_request,
            confidence=0.88,
            parameters={
                "learning_type": LearningType.WORKFLOW_PLAYBOOK,
                "draft_title": "Playbook из Telegram",
                "draft_description": raw[:2000],
            },
            needs_confirmation=True,
        )

    if low.startswith("запомни") or "измени поведение" in low or "как правило" in low:
        body = raw
        for prefix in ("запомни:", "запомни", "измени поведение:", "измени поведение"):
            if low.startswith(prefix):
                body = raw[len(prefix) :].strip(" :\t")
                break
        return NLRouterDecision(
            mode=RouterModeEnum.learning,
            intent=IntentEnum.learning_request,
            confidence=0.9,
            parameters={
                "learning_type": LearningType.BEHAVIOR_RULE,
                "suggested_rule_text": body[:4000] or raw,
            },
            needs_confirmation=True,
        )

    if "сохрани" in low and ("регламент" in low or "документ" in low or "инструкц" in low):
        return NLRouterDecision(
            mode=RouterModeEnum.learning,
            intent=IntentEnum.learning_request,
            confidence=0.85,
            parameters={
                "learning_type": LearningType.KNOWLEDGE_DOCUMENT,
                "body": raw[:12000],
            },
            needs_confirmation=True,
        )

    if "клиент" in low and ("дедлайн" in low or "любит" in low or "предпочитает" in low):
        return NLRouterDecision(
            mode=RouterModeEnum.learning,
            intent=IntentEnum.learning_request,
            confidence=0.82,
            parameters={
                "learning_type": LearningType.KNOWLEDGE_NOTE,
                "note_text": raw[:4000],
            },
            needs_confirmation=True,
        )

    if any(x in low for x in ("что умеешь", "что ты умеешь", "помощь")):
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.help_capabilities,
            confidence=0.9,
            parameters={},
            needs_confirmation=False,
        )

    if any(x in low for x in ("статус систем", "всё ли работает", "все ли работает", "диагност")):
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.diagnostics_status,
            confidence=0.88,
            parameters={},
            needs_confirmation=False,
        )

    if any(x in low for x in ("какие чаты", "список чат", "группы ты видишь")):
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.list_chats,
            confidence=0.86,
            parameters={},
            needs_confirmation=False,
        )

    if any(x in low for x in ("какие проект", "список проект", "активные проект")):
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.list_projects,
            confidence=0.86,
            parameters={},
            needs_confirmation=False,
        )

    if any(x in low for x in ("кто без ответа", "что горит", "просроч", "инцидент")) or (
        "sla" in low and "что" in low
    ):
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.open_risks_or_sla,
            confidence=0.87,
            parameters={},
            needs_confirmation=False,
        )

    if "найди" in low or ("поиск" in low and "баз" in low):
        q = raw
        for prefix in ("найди в базе знаний", "найди", "поиск"):
            if low.startswith(prefix):
                q = raw[len(prefix) :].strip(" :")
                break
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.kb_search,
            confidence=0.84,
            parameters={"query": q[:2000] or raw},
            needs_confirmation=False,
        )

    if any(x in low for x in ("что в базе знаний", "что мы знаем про", "как у нас про")):
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.kb_ask,
            confidence=0.83,
            parameters={"question": raw[:4000]},
            needs_confirmation=False,
        )

    guess = _extract_project_guess(raw)
    if guess or ("проект" in low and len(low) > 8):
        params: dict[str, Any] = {**_period_params(low), "scope": "one_project"}
        params["project_name_guess"] = guess
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.project_digest,
            confidence=0.8 if guess else 0.55,
            parameters=params,
            needs_confirmation=False,
            clarify_question=None if guess else "По какому проекту сделать сводку? Укажите slug или название.",
        )

    if any(
        x in low
        for x in (
            "отчёт",
            "отчет",
            "сводк",
            "по стате",
            "за сегодня",
            "за вчера",
            "за неделю",
            "что нового",
        )
    ):
        return NLRouterDecision(
            mode=RouterModeEnum.business_action,
            intent=IntentEnum.studio_digest,
            confidence=0.88,
            parameters={**_period_params(low), "scope": "all_chats"},
            needs_confirmation=False,
        )

    if any(x in low for x in ("привет", "здравств", "ты тут", "hello")):
        return NLRouterDecision(
            mode=RouterModeEnum.casual,
            intent=IntentEnum.casual_or_assistant,
            confidence=0.75,
            parameters={},
            needs_confirmation=False,
        )

    return NLRouterDecision(
        mode=RouterModeEnum.clarify,
        intent=IntentEnum.unclear,
        confidence=0.4,
        parameters={},
        needs_confirmation=False,
        clarify_question="Уточните: отчёт за период, риски/SLA, проект, поиск по базе знаний или обучение (запомни/научись)?",
    )
