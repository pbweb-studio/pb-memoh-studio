# Текущая задача

## Фаза 4 — Event Mirror

**Цель:** зеркалирование релевантных событий из Memoh (или согласованной границы) в Studio: модель событий, транспорт, идемпотентность и связь с внутренними сервисами Studio (в т.ч. Response Queue **по отдельному плану**, без дублирования логики Memoh).

**Зависимости:** работающий каркас Фазы 3 (API, Postgres, Redis, Celery); **не** подключать Telegram runtime до явного решения в `docs/06_DECISIONS.md`.

**Ограничение:** любые правки Memoh (`internal/channel/adapters/telegram`, `internal/channel/inbound.go`, `internal/channel/inbound/channel.go` и т.д.) — только после явного ADR и выбора варианта A/B/C.
