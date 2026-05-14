# Active context

**Сейчас:** фаза **8a** в Studio — SLA по зеркалу `studio_messages`: `studio_sla_policies`, `studio_sla_incidents`, детектор first response для `client_chat` / `project_chat`, разрешение при ответе бота, уведомления только в активную control group; Celery `detect_sla_incidents`; админ `/sla/*`; env `STUDIO_SLA_*` в compose. Поверх 7a–7b: control commands, сводки 6a–6d. Memoh не менялся; второго бота и polling/webhook Studio нет.

**Ветка:** `pb-studio/main`.

**Memoh:** не менялся в 8a.

**Следующий шаг:** полная **фаза 8** по плану или **6+** / **7** только по отдельной постановке.
