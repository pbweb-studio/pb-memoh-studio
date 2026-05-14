# Текущая задача

## После фазы 6d (доставка готовых сводок в control group)

**Статус:** для строк `studio_chat_summaries` со `status=generated` добавлена доставка в Telegram control group через Bot API `sendMessage` (тот же `TELEGRAM_BOT_TOKEN`): поля `delivery_*`, ретраи `STUDIO_SUMMARY_DELIVERY_MAX_RETRIES`, флаг `STUDIO_SUMMARY_DELIVERY_ENABLED`. Админ: `POST /summaries/{id}/deliver-control-group`, `POST /summaries/deliver-pending`; Celery `deliver_pending_chat_summaries`. **Без** Memoh, **без** LLM/RAG, **без** второго бота и без изменений polling/webhook.

**Следующий шаг (не начинать без задачи):** фаза **6+** (LLM, иные каналы доставки) **или** другие фазы плана.

**Ограничение:** не подключать внешний LLM и RAG без постановки; Memoh не менять без ADR; SLA / проекты / Studio Admin — вне scope.
