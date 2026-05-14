from __future__ import annotations


class ControlCommandStatus:
    PENDING = "pending"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class ControlCommandName:
    SUMMARY_TODAY = "summary_today"
    SUMMARY_YESTERDAY = "summary_yesterday"
    SUMMARY_PERIOD = "summary_period"
    SUMMARY_LATEST = "summary_latest"
    SUMMARY_HELP = "summary_help"
    UNKNOWN = "unknown"


SUMMARY_HELP_TEXT = """Команды сводок (Studio, только из управляющей группы):
/summary_help — этот текст
/summary_today <studio_chat_uuid> — сводка за сегодня (UTC)
/summary_yesterday <studio_chat_uuid> — за вчера (UTC)
/summary_period <studio_chat_uuid> <YYYY-MM-DD> <YYYY-MM-DD> — период по календарным дням UTC
/summary_latest <studio_chat_uuid> — последняя generated-сводка по чату
"""
