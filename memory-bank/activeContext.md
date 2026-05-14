# Active context

**Сейчас:** фаза **8c** в Studio — SLA уведомления в control group: таблица `studio_sla_notification_events`, поля инцидента `next_notification_at` / `suppressed_notification_count` / `last_notification_reason`; `sla/notifications.py` (cooldown + `max(cooldown, followup_minutes)`, digest за цикл, обрезка текста); Alembic `010`; API `GET /sla/notification-events`, `POST /sla/incidents/{id}/notify`, фильтры на `GET /sla/incidents`; env `STUDIO_SLA_NOTIFICATION_*`. Поверх 8a–8b. Memoh не менялся.

**Ветка:** `pb-studio/main`.

**Следующий шаг:** **6+** или **9** — по отдельной постановке.
