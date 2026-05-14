# Текущая задача

## После фазы 8a (SLA-инфраструктура по чатам без LLM)

**Статус:** политики и инциденты в БД; детектор по зеркалу `studio_messages` (только `client_chat` / `project_chat`); first response по активной policy или `STUDIO_SLA_DEFAULT_FIRST_RESPONSE_MINUTES`; разрешение инцидента при ответе бота или смене «хвоста» входящих; уведомления только в control group при `STUDIO_SLA_ENABLED` и наличии CG; Celery `detect_sla_incidents`; админ REST `/sla/*`. Memoh не менялся.

**Следующий шаг:** полная **фаза 8** по плану (рабочие часы, антиспам, mute и т.д.) или **6+** / **7** — только по отдельной постановке.

**Ограничение:** внешний LLM/RAG, проекты, Studio Admin UI — вне scope до отдельной фазы.
