#!/usr/bin/env bash
# Восстановление Postgres Studio из логического дампа (.sql.gz), созданного backup-postgres.sh.
# Останавливает API/worker/beat, заливает дамп через psql в контейнер, затем поднимает сервисы.
#
# Usage (из корня репозитория на сервере):
#   export COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"
#   ./deploy/scripts/restore-postgres.sh ./backups/pb_studio_pg_YYYYMMDDTHHMMSSZ.sql.gz
#
# ВНИМАНИЕ: перезапишет текущую БД (с учётом --clean в дампе). Сделайте свежий бэкап перед restore.

set -euo pipefail
DUMP="${1:?usage: $0 path/to/pb_studio_pg_*.sql.gz}"
if [[ ! -f "$DUMP" ]]; then
  echo "ERROR: file not found: $DUMP" >&2
  exit 1
fi

COMPOSE_CMD="${COMPOSE:-docker compose --env-file .env.prod -f docker-compose.prod.yml}"

echo "Stopping studio-api, studio-worker, studio-beat ..."
$COMPOSE_CMD stop studio-api studio-worker studio-beat

echo "Restoring from $DUMP ..."
gunzip -c "$DUMP" | $COMPOSE_CMD exec -T studio-postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'

echo "Starting studio-api, studio-worker, studio-beat ..."
$COMPOSE_CMD start studio-api studio-worker studio-beat

echo "Restore finished. Verify with GET /health and smoke script."
