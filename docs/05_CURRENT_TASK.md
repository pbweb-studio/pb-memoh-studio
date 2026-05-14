# Текущая задача

## Фаза 4b+ — транспорт Event Mirror и интеграция с Memoh

**Цель:** подать события в уже работающий ingest Studio (`POST /events/telegram` или внутренний вызов) из согласованной границы (webhook/proxy к Memoh, sidecar, и т.д.) **без** правок Memoh до выбора A/B/C в `docs/06_DECISIONS.md`.

**Зависимости:** Фаза 4a (таблицы + HTTP ingest); вариант интеграции зафиксировать в ADR.

**Ограничение:** не патчить `internal/channel/adapters/telegram`, `internal/channel/inbound.go`, `telegram.go` без явного решения пользователя.
