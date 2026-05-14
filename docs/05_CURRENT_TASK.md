# Текущая задача

## После фазы 6c (продуктовый API сводок без LLM и без Telegram-доставки)

**Статус:** под `STUDIO_ADMIN_TOKEN` доступны `POST /summaries/chat/{studio_chat_id}/today|yesterday|period` и `GET /summaries/chat/{studio_chat_id}/latest`: идемпотентно план + шаблонная генерация из Event Mirror (UTC); при `failed` за период — 409. Требуется `STUDIO_SUMMARY_GENERATION_ENABLED=true`. **Без** Memoh, **без** внешнего LLM, **без** `sendMessage` сводок.

**Следующий шаг (не начинать без задачи):** фаза **6+** (LLM и/или доставка сводок в Telegram) **или** другие фазы плана.

**Ограничение:** не подключать внешний LLM и RAG без постановки; Memoh не менять без ADR; SLA / проекты / Studio Admin — вне scope текущей фазы.
