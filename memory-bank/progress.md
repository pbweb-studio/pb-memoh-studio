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
| 9b Project digest from chat summaries (no LLM for digest text) | Done |
| 10a Knowledge base documents/versions/chunks (no embeddings) | Done |
| 10b KB parse pipeline (pending, plain/md, unsupported MIME) | Done |
| 10c KB embeddings + pgvector search (no LLM/RAG answers) | Done |
| 10d KB external OpenAI-compatible embedding provider | Done |
| 10e KB RAG question answering MVP (ask API + /kb_ask) | Done |
| 10f KB HTTP upload + optional Docling (pdf/docx) | Done |
| 10g KB Telegram document import (control group) | Done |
| 11a Assistant rules storage + API + /rule_* (no LLM apply) | Done |
| 11b Assistant rules in KB RAG prompt + applied_rule_ids | Done |
| 12a Telegram Desktop JSON → Event Mirror import | Done |
| 13a Studio Admin UI skeleton (read-only /admin) | Done |
| 13b Studio Admin UI details + safe forms | Done |
| 13c Studio Admin UI polish (filters, pagination, UX) | Done |
| 14a Prod compose + env example + runbook/backup (no deploy) | Done |
| 6+ Сводки (LLM / доставка в Telegram) и прочее | Pending |

**Последнее:** фаза 14a — `docker-compose.prod.yml`, `.env.prod.example`, `deploy/`, `docs/08_RUNBOOK_PRODUCTION.md`; полный `pytest tests/` **289** passed (Docker).
