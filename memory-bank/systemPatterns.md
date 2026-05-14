# System patterns

- **Single bot** — все пользовательские сценарии через одного Telegram-бота.
- **Control group** — админ-команды и системные уведомления только туда (или только лог, если не настроено).
- **Studio Layer owns business state** — чаты, сообщения, raw updates, RAG, SLA, rules, audit.
- **Memoh** — reasoning/toolcalls; связь со Studio через MCP/API.
- **Event Mirror** — идемпотентная запись Telegram updates (`update_id`) + сущности чатов/сообщений.
- **Response Queue** — per-chat последовательность, debounce, явные статусы turn; «глазик» не финальный статус.
- **SLA** — чистая логика в worker, не heartbeat Memoh.
