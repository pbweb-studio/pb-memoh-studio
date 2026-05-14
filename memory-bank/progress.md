# Progress

| Фаза | Статус |
|------|--------|
| 0 Bootstrap | Done |
| 1 Recon Memoh | Done |
| 2a Response Queue | Done |
| 3 Studio skeleton | Done |
| 4a Event Mirror ingest | Done |
| ADR интеграции TG→Studio (перед 4b) | Done |
| 4b Транспорт Memoh → ingest (вариант C) | Done |
| 5+ | Pending |

**Последнее:** утверждён и реализован вариант **C** — тонкий hook в Telegram adapter (без второго бота, без gateway, без смены webhook/polling); Studio остаётся источником raw/normalize/опциональной очереди.
