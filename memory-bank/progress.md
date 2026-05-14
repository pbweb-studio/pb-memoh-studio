# Progress

| Фаза | Статус |
|------|--------|
| 0 Bootstrap | Done |
| 1 Recon Memoh | Done |
| 2a Response Queue (Studio DB, без Memoh) | Done |
| 2b/3 Studio API + Celery + интеграция turn | Next |
| 4+ | Pending |

**Последнее:** реализованы модели `studio_response_turns` / `studio_inbound_messages`, `QueueService` (debounce, per-chat ordering, dedupe, dispatch с SKIP LOCKED), контракт `TurnProcessor`, 10 тестов.
