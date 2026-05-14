# Текущая задача

## После фазы 8c (антиспам SLA-уведомлений)

**Статус:** аудит `studio_sla_notification_events`; rate-limit и digest для `sendMessage` в активную control group; cooldown + `followup_minutes` через `max`; ручной `POST /sla/incidents/{id}/notify`; фильтры на списке инцидентов; Alembic `010`. Memoh не менялся.

**Следующий шаг:** **6+** (LLM/доставка сводок и т.д.) или **9** (проекты) — только по отдельной постановке.
