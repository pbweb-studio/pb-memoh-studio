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
"""
