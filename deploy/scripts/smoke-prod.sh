#!/usr/bin/env bash
# Smoke checks для Studio API после старта compose (на сервере или локально с проброшенным портом).
# Не печатает токены. Использует curl.
# Не оборачивать вызов в bash -x / set -x, если передаёте STUDIO_ADMIN_TOKEN в окружении — иначе токен может попасть в лог трассировки.
#
# Переменные:
#   STUDIO_BASE_URL   — базовый URL API (по умолчанию http://127.0.0.1:8000)
#   STUDIO_ADMIN_TOKEN — опционально; если задан, проверяется GET /projects с Bearer
#
# Пример:
#   export STUDIO_BASE_URL=https://studio.example.com
#   export STUDIO_ADMIN_TOKEN='***'   # из секрет-хранилища, не в истории shell
#   ./deploy/scripts/smoke-prod.sh

set -euo pipefail

BASE="${STUDIO_BASE_URL:-http://127.0.0.1:8000}"
BASE="${BASE%/}"

echo "Smoke: BASE_URL=${BASE} (no secrets printed)"

code_health="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/health" || true)"
if [[ "$code_health" != "200" ]]; then
  echo "FAIL: GET /health expected 200, got ${code_health}"
  exit 1
fi
echo "OK: GET /health → 200"

code_login="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/admin/login" || true)"
if [[ "$code_login" != "200" ]]; then
  echo "FAIL: GET /admin/login expected 200, got ${code_login}"
  exit 1
fi
echo "OK: GET /admin/login → 200"

# Неавторизованный HTML-запрос к защищённой странице → редирект на логин (или 503 если токен админки не задан на сервере)
code_admin="$(curl -sS -o /dev/null -w '%{http_code}' \
  -H 'Accept: text/html' \
  "${BASE}/admin/chats" || true)"
if [[ "$code_admin" == "302" ]] || [[ "$code_admin" == "301" ]]; then
  echo "OK: GET /admin/chats (HTML) → redirect (login)"
elif [[ "$code_admin" == "503" ]]; then
  echo "WARN: GET /admin/chats → 503 (STUDIO_ADMIN_TOKEN may be unset on server)"
else
  echo "FAIL: GET /admin/chats (HTML) expected 302/301 or 503, got ${code_admin}"
  exit 1
fi

if [[ -n "${STUDIO_ADMIN_TOKEN:-}" ]]; then
  code_api="$(curl -sS -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${STUDIO_ADMIN_TOKEN}" \
    -H 'Accept: application/json' \
    "${BASE}/projects" || true)"
  if [[ "$code_api" != "200" ]]; then
    echo "FAIL: GET /projects with Bearer expected 200, got ${code_api}"
    exit 1
  fi
  echo "OK: GET /projects (Bearer) → 200"
else
  echo "SKIP: STUDIO_ADMIN_TOKEN not set — Bearer API check skipped"
fi

echo "Smoke: all checks passed."
