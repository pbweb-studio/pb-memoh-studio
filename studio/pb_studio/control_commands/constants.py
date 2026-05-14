from __future__ import annotations


class ControlCommandStatus:
    PENDING = "pending"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"
    FAILED_ACCESS_DENIED = "failed_access_denied"


class ControlCommandName:
    SUMMARY_TODAY = "summary_today"
    SUMMARY_YESTERDAY = "summary_yesterday"
    SUMMARY_PERIOD = "summary_period"
    SUMMARY_LATEST = "summary_latest"
    SUMMARY_HELP = "summary_help"
    SUMMARY_CHATS = "summary_chats"
    SUMMARY_ALL_TODAY = "summary_all_today"
    SUMMARY_ALL_YESTERDAY = "summary_all_yesterday"
    UNKNOWN = "unknown"
    PROJECT_HELP = "project_help"
    PROJECT_LIST = "project_list"
    PROJECT_CREATE = "project_create"
    PROJECT_BIND = "project_bind"
    PROJECT_UNBIND = "project_unbind"
    PROJECT_CHATS = "project_chats"
    PROJECT_DIGEST_TODAY = "project_digest_today"
    PROJECT_DIGEST_YESTERDAY = "project_digest_yesterday"
    PROJECT_DIGEST_PERIOD = "project_digest_period"
    PROJECT_DIGEST_LATEST = "project_digest_latest"
    KB_HELP = "kb_help"
    KB_LIST = "kb_list"
    KB_GET = "kb_get"
    KB_ADD = "kb_add"


# Лимиты UX для Telegram sendMessage (оставляем запас под «обрезано»)
TELEGRAM_TEXT_SAFE_MAX = 4000
SUMMARY_CHATS_MAX_LINES = 35
SUMMARY_AGG_SNIPPET_CHARS = 220


SUMMARY_HELP_TEXT = """Команды сводок (Studio, только из управляющей группы):
/summary_help — этот текст
/summary_chats — список зеркалируемых чатов (кроме активной control group)
/summary_all_today — сводка за сегодня (UTC) по всем чатам, кроме control group
/summary_all_yesterday — то же за вчера (UTC)
/summary_today <studio_chat_uuid> — сводка за сегодня (UTC) по одному чату
/summary_yesterday <studio_chat_uuid> — за вчера (UTC)
/summary_period <studio_chat_uuid> <YYYY-MM-DD> <YYYY-MM-DD> — период по календарным дням UTC
/summary_latest <studio_chat_uuid> — последняя generated-сводка по чату

Проекты: /project_help
База знаний: /kb_help
"""


PROJECT_HELP_TEXT = """Команды проектов (Studio, только из управляющей группы):
/project_help — этот текст
/project_list — список проектов
/project_create <slug> <название> — создать проект (slug: a-z, 0-9, -, _)
/project_bind <project_slug> <studio_chat_uuid> — привязать чат к проекту
/project_unbind <project_slug> <studio_chat_uuid> — отвязать чат (связь деактивируется)
/project_chats <project_slug> — чаты проекта

Дайджесты (агрегат сводок по проекту):
/project_digest_today <project_slug>
/project_digest_yesterday <project_slug>
/project_digest_period <project_slug> <YYYY-MM-DD> <YYYY-MM-DD>
/project_digest_latest <project_slug>

База знаний: /kb_help
"""

KB_HELP_TEXT = """Команды базы знаний (Studio, только из управляющей группы; без RAG/LLM):
/kb_help — этот текст
/kb_list — список документов KB
/kb_get <document_uuid> — карточка документа и активная версия
/kb_add <title> | <text> — новый документ (manual) и первая версия из текста (разбиение на чанки в Studio)

Требуется STUDIO_KB_ENABLED=true. Документы и API: GET/POST /knowledge/... под STUDIO_ADMIN_TOKEN.
"""
