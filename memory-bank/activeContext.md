# Active context

**Сейчас:** фаза **8b** в Studio — SLA календарь: рабочие дни/часы, timezone policy, holidays, расчёт `due_at` через `calculate_due_at` при `STUDIO_SLA_WORKING_HOURS_ENABLED`; mute на policy (`is_muted`, `muted_until`) блокирует только новые инциденты; API `PATCH /sla/policies/{id}`, mute/unmute; Alembic `009`. Поверх 8a: инциденты, детектор, Celery. Memoh не менялся.

**Ветка:** `pb-studio/main`.

**Следующий шаг:** остаток **фазы 8** по плану или **6+** по постановке.
