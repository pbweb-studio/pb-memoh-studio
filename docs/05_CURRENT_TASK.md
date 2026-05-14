# Текущая задача

## После фазы 14b (deploy readiness, без деплоя)

**Статус:** расширены `.env.prod.example` (REQUIRED/optional/secret, feature flags), [`docs/08_RUNBOOK_PRODUCTION.md`](08_RUNBOOK_PRODUCTION.md) (полный checklist), скрипты `deploy/scripts/` (smoke, validate env, restore Postgres, backup KB volume), обновлены Caddy placeholder и [`deploy/BACKUP_RESTORE.md`](deploy/BACKUP_RESTORE.md). Memoh и логика приложения не менялись; **деплой на VPS не выполнялся**.

**Следующий шаг:** по постановке — **14+** (реальный деплой + Caddy/TLS после согласования домена), **6+**, **13+** или доработки Studio.
