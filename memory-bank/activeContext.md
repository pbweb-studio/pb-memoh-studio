# Active context

**Сейчас:** фаза **6b** в Studio — шаблонная генерация `summary_text` для pending `studio_chat_summaries` из Event Mirror; Celery `generate_pending_chat_summaries`; `POST /summaries/generate-pending`, `POST /summaries/{id}/generate`; env `STUDIO_SUMMARY_*`. Без внешнего LLM, без Telegram send для сводок.

**Ветка:** `pb-studio/main`.

**Memoh:** не менялся в 6b.

**Следующий шаг:** фаза 6+ только по отдельной постановке.
