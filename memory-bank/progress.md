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
| 4b Проверка (go test / pytest / compose config) | Done |
| 5a Управляющая группа (Studio) | Done |
| 5b Outbound system notifications → control group | Done |
| 6+ Сводки и прочее | Pending |

**Последнее:** хвост 5b — `docker-compose.local.yml`: TELEGRAM + флаги доставки для `studio-api` / `studio-worker`; compose config + pytest ok.
