# План внедрения (фазы 0–14)

Детализация шагов Memoh (Telegram adapter, Response Queue, Event Mirror) добавляется в **Фазе 1** после разведки кода.

| Фаза | Содержание |
|------|------------|
| 0 | Bootstrap: Memoh + каркас `studio/`, docs, memory-bank, rules, compose studio-infra |
| 1 | Техническая разведка Memoh (Telegram, MCP, «глазик»), обновление этого документа |
| 2 | Response Queue + debounce + статусы + тесты |
| 3 | Studio skeleton: FastAPI, Postgres, Redis, Celery, Alembic, `/health`, compose |
| 4 | Event Mirror: raw updates, chats/messages, lifecycle, без системных сообщений в клиентских чатах |
| 5 | Управляющая группа, роли, уведомления только туда |
| 6 | Сводка «сегодня» из Studio DB |
| 7 | Сводки из управляющей группы (чат / проект / все), права |
| 8 | SLA (код, не GPT), рабочие часы, антиспам, mute |
| 9 | Проекты: bind/list/digest |
| 10 | База знаний: Docling, embeddings, pgvector |
| 11 | Правила: save/list/disable/audit |
| 12 | Импорт истории Telegram Desktop JSON |
| 13 | Studio Admin (HTMX/Jinja/Bootstrap) |
| 14 | Prod compose, Caddy, runbook, backup (деплой только с подтверждением) |
