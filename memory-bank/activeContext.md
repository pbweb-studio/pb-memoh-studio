# Active context

**Сейчас:** фаза **9b** в Studio — project digest: `studio_project_digests` (Alembic `012`); `pb_studio/project_digests`; API `/projects/{id}/digests*`, `/project-digests/*`; команды `/project_digest_*` из active control group; Celery `generate_daily_project_digests`, `deliver_pending_project_digests` (+ по-прежнему цикл `/project_*`/`/summary_*`). Memoh не менялся.

**Ветка:** `pb-studio/main`.

**Следующий шаг:** **6+** (LLM/продукт) или **RAG/база знаний** — по отдельной постановке.
