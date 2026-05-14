# Текущая задача

## Фаза 2 — Response Queue (Studio + интеграция с Memoh)

**Цель:** очередь обработки входящих сообщений per-chat с debounce 2–4 с, склейка turn, статусы (`answered`, `ignored_by_policy`, `failed_with_error`, `cancelled_by_newer_request`), наблюдаемость; не терять сообщения.

**Входные данные:** разведка в [`docs/03_IMPLEMENTATION_PLAN.md`](docs/03_IMPLEMENTATION_PLAN.md), варианты интеграции — [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md).

**Шаги (черновик):**

1. Поднять каркас Studio (можно начать с Фазы 3 параллельно, если удобнее): FastAPI + Celery + таблицы очереди.
2. Выбрать вариант A/B/C и зафиксировать ADR в `docs/06_DECISIONS.md`.
3. Реализовать MVP очереди + тесты.

**Ограничение:** не кастомить heartbeat Memoh; не ломать upstream без записи в `06_DECISIONS.md`.
