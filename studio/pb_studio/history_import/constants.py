from __future__ import annotations


class HistoryImportSourceType:
    TELEGRAM_DESKTOP_JSON = "telegram_desktop_json"


class HistoryImportJobStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Маркер в raw_message для трассировки (не Bot API)
RAW_STUDIO_HISTORY_IMPORT = "studio_history_import"
