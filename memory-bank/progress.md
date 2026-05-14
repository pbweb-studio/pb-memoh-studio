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
| 6c Product summaries API (today/yesterday/period/latest, no LLM, no TG send) | Done |
| 6d Summary delivery to control group (sendMessage, no Memoh/LLM) | Done |
| 7a Control group summary commands via Event Mirror | Done |
| 7b UX summary commands + ACL in control group | Done |
| 8a SLA infra (policies + incidents, mirror, no LLM) | Done |
| 8b SLA working hours + mute on policies | Done |
| 8c SLA notification antispam + digest + audit | Done |
| 9a Projects + project↔chat binding (Studio DB, no RAG) | Done |
| 6+ Сводки (LLM / доставка в Telegram) и прочее | Pending |

**Последнее:** фаза 9a — `pb_studio/projects`, migration 011, `/projects` API, `/project_*` control commands, Celery alias `process_control_group_commands`; pytest **169** passed; `docker compose -f docker-compose.local.yml config` ok.
