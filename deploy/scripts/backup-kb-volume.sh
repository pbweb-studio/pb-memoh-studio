#!/usr/bin/env bash
# Архив volume загрузок KB (отдельно от дампа Postgres).
# Имя volume по умолчанию соответствует project name из docker-compose.prod.yml (name: pb-studio-prod).
#
# Usage (из корня репозитория):
#   mkdir -p backups
#   ./deploy/scripts/backup-kb-volume.sh ./backups
#
# Переопределение имени volume:
#   KB_VOLUME_NAME=my-custom-volume ./deploy/scripts/backup-kb-volume.sh ./backups

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST_DIR="${1:-$ROOT/backups}"
mkdir -p "$DEST_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_NAME="pb_studio_kb_${TS}.tgz"
OUT="$DEST_DIR/$OUT_NAME"
DEST_ABS="$(cd "$DEST_DIR" && pwd)"

# Compose v2: {project}_{volume_key}; при name: pb-studio-prod в compose — см. docker volume ls
VOL="${KB_VOLUME_NAME:-pb-studio-prod_pb_studio_prod_kb_uploads}"

echo "Archiving Docker volume: $VOL → $OUT"
docker run --rm \
  -v "${VOL}:/kb:ro" \
  -v "${DEST_ABS}:/out" \
  alpine:3.20 \
  tar czf "/out/${OUT_NAME}" -C /kb .

echo "Done: $OUT"
echo "Restore: остановить запись (studio-api/worker), затем распаковать в пустой volume — см. deploy/BACKUP_RESTORE.md"
