# Текущая задача

## Фаза 2b / 3 — Studio runtime вокруг очереди

**Цель:** HTTP-приём (или внутренний вызов) для `InboundEnqueue`, фоновые задачи Celery: периодический `flush_due_turns`, `dispatch_next` с реализацией `TurnProcessor` (пока заглушка или вызов Memoh после выбора A/B/C).

**Зависимости:** Postgres Studio (уже есть compose), Redis; **не** подключать Telegram до Event Mirror (Фаза 4).

**Ограничение:** любые правки Memoh (`internal/channel/adapters/telegram`, `internal/channel/inbound.go`, `internal/channel/inbound/channel.go` и т.д.) — только после явного ADR в [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md) и ответа на вопросы интеграции.
