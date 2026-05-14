# Текущая задача

## После фазы 6b (шаблонная генерация summary_text)

**Статус:** для `pending` заданий `studio_chat_summaries` заполняется детерминированный `summary_text` из Event Mirror (шаблон); `POST /summaries/generate-pending`, `POST /summaries/{id}/generate`; Celery `generate_pending_chat_summaries`; флаг `STUDIO_SUMMARY_GENERATION_ENABLED`. **Без** внешнего LLM API, **без** отправки сводок в Telegram.

**Следующий шаг (не начинать без задачи):** фаза **6+** (LLM / продукт / доставка сводок) **или** другие фазы плана.

**Ограничение:** не подключать внешний LLM и RAG без постановки; Memoh не менять без ADR; SLA / проекты / Studio Admin — вне scope.
