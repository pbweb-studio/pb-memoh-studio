#!/usr/bin/env bash
# memoh-orphan-cleanup.sh — watchdog против orphan user-turn в bot_history_messages.
#
# КОРРЕКТНАЯ ОБЛАСТЬ ПРИМЕНЕНИЯ: ТОЛЬКО DM-сессии (conversation_type='private'
# в bot_channel_routes). В DM политика чёткая: каждый user-turn должен иметь
# assistant/tool ответ. Если ответа нет старше GRACE_SECONDS — это и есть
# повисший orphan от сбоя generation/polling/контейнера.
#
# В ГРУППОВЫХ чатах watchdog НЕ работает: там бот по политике (ACL/role —
# client_chat / service_chat / отсутствие mention) молчит на ~99% сообщений,
# и трактовать любой user-row как orphan — катастрофа: можно стереть
# историю активного рабочего чата.
#
# Скрипт идемпотентен (no-op если orphan-ов нет) и не трогает свежие user-row
# (моложе GRACE_SECONDS).
#
# Использование:
#   ./deploy/scripts/memoh-orphan-cleanup.sh           # реальный прогон
#   GRACE_SECONDS=300 ./deploy/scripts/memoh-orphan-cleanup.sh
#   DRY_RUN=1 ./deploy/scripts/memoh-orphan-cleanup.sh # только показать
#
# Запускается из systemd timer (см. deploy/systemd/memoh-orphan-cleanup.*).
set -euo pipefail

CONTAINER="${MEMOH_PG_CONTAINER:-memoh-jar-postgres-1}"
PG_USER="${MEMOH_PG_USER:-memoh}"
PG_DB="${MEMOH_PG_DB:-memoh}"
GRACE_SECONDS="${GRACE_SECONDS:-120}"
DRY_RUN="${DRY_RUN:-0}"
LOG_FILE="${LOG_FILE:-/var/log/memoh-orphan-cleanup.log}"

ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }

log() {
  printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE" >&2
}

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  log "container ${CONTAINER} not running, skip"
  exit 0
fi

# orphan = user-row в DM-сессии (route.conversation_type='private') старше
# GRACE_SECONDS, у которой в той же сессии нет assistant/tool строки с
# created_at >= user.created_at.
SQL_FIND="SELECT u.id::text, u.session_id::text, u.created_at, COALESCE(LEFT(u.display_text, 80), '') AS preview
FROM bot_history_messages u
JOIN bot_sessions s ON s.id = u.session_id
JOIN bot_channel_routes r ON r.id = s.route_id
WHERE u.role = 'user'
  AND u.created_at < now() - interval '${GRACE_SECONDS} seconds'
  AND s.deleted_at IS NULL
  AND r.conversation_type = 'private'
  AND NOT EXISTS (
    SELECT 1 FROM bot_history_messages h
    WHERE h.session_id = u.session_id
      AND h.role IN ('assistant','tool')
      AND h.created_at >= u.created_at
  )
ORDER BY u.created_at;"

ORPHANS=$(docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -A -t -F '|' -c "$SQL_FIND" || true)
if [[ -z "${ORPHANS//[[:space:]]/}" ]]; then
  exit 0
fi

COUNT=$(printf '%s\n' "$ORPHANS" | wc -l | tr -d '[:space:]')
log "found ${COUNT} orphan DM user-row(s) older than ${GRACE_SECONDS}s"
printf '%s\n' "$ORPHANS" | while IFS='|' read -r oid session created preview; do
  [[ -z "${oid:-}" ]] && continue
  log "orphan id=${oid} session=${session} created=${created} preview=\"${preview}\""
done

if [[ "$DRY_RUN" == "1" ]]; then
  log "DRY_RUN=1, no DELETE"
  exit 0
fi

SQL_DEL="WITH orphans AS (
  SELECT u.id
  FROM bot_history_messages u
  JOIN bot_sessions s ON s.id = u.session_id
  JOIN bot_channel_routes r ON r.id = s.route_id
  WHERE u.role = 'user'
    AND u.created_at < now() - interval '${GRACE_SECONDS} seconds'
    AND s.deleted_at IS NULL
    AND r.conversation_type = 'private'
    AND NOT EXISTS (
      SELECT 1 FROM bot_history_messages h
      WHERE h.session_id = u.session_id
        AND h.role IN ('assistant','tool')
        AND h.created_at >= u.created_at
    )
)
DELETE FROM bot_history_messages WHERE id IN (SELECT id FROM orphans) RETURNING id;"

DELETED=$(docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -A -t -c "$SQL_DEL" | grep -c '^[0-9a-f]' || true)
log "deleted ${DELETED} orphan DM row(s)"
