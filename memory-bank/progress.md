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
| 6a Summaries infra (DB + planner, no LLM) | Done |
| 6b Template summary_text generation (no LLM API, no TG send) | Done |
| 6+ Сводки (LLM / продукт / доставка) и прочее | Pending |

**Последнее:** фаза 6b — generator, Celery generate_pending, admin generate endpoints; pytest 66 passed (Docker).
