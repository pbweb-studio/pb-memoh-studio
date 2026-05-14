# Active context

**Сейчас:** фаза **14b** — deploy readiness **без фактического деплоя**: расширенный `docs/08_RUNBOOK_PRODUCTION.md`, `.env.prod.example` (REQUIRED/optional/secret + feature flags), `deploy/scripts/validate_env_prod.py`, `smoke-prod.sh`, `validate-env-prod.sh`, `restore-postgres.sh`, `backup-kb-volume.sh`, обновлены `deploy/BACKUP_RESTORE.md` и `deploy/caddy/Caddyfile.example`. Memoh и код приложения Studio не менялись.

**Ветка:** `pb-studio/main`.

**Следующий шаг:** **14+** (реальный деплой на согласованный VPS + Caddy/TLS после домена) или **6+** / **13+** / **10+** — по постановке.
