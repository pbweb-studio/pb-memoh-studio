#!/usr/bin/env bash
# Логический дамп Postgres Studio (production volume / контейнер pb-studio-prod-postgres).
# Не выполняет деплой; запускать вручную на сервере с установленным Docker.
#
# Использование (из корня репозитория на сервере):
#   export COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"
#   mkdir -p backups
#   ./deploy/scripts/backup-postgres.sh ./backups
#
set -euo pipefail
DEST_DIR="${1:-./backups}"
mkdir -p "$DEST_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$DEST_DIR/pb_studio_pg_${TS}.sql.gz"
echo "Writing $OUT ..."
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T studio-postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists' \
  | gzip > "$OUT"
echo "Done: $OUT"
