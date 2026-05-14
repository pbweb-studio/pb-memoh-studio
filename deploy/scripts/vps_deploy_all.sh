#!/usr/bin/env bash
# Полный деплой на VPS: Studio (prod compose) + Memoh + Caddy из репо + smoke.
# Секреты не печатаются. Без set -x.
# Запуск на сервере: bash /opt/pb-studio/pb-memoh-studio/deploy/scripts/vps_deploy_all.sh

set -eu
set +x

REPO="${REPO:-/opt/pb-studio/pb-memoh-studio}"
MEMOH_ROOT="${MEMOH_ROOT:-/opt/pb-studio/memoh}"

cd "$REPO"

echo "=== git fetch + reset ==="
git fetch origin
git reset --hard origin/pb-studio/main
git rev-parse HEAD

echo "=== validate .env.prod ==="
python3 deploy/scripts/validate_env_prod.py .env.prod

export MEMOH_ROOT

echo "=== Studio: pull, build, up ==="
docker compose --env-file .env.prod -f docker-compose.prod.yml pull
docker compose --env-file .env.prod -f docker-compose.prod.yml build \
  studio-migrate studio-api studio-worker studio-beat
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

echo "=== Memoh: prepare runtime ==="
python3 deploy/scripts/prepare_memoh_runtime.py \
  --studio-env /opt/pb-studio/pb-memoh-studio/.env.prod \
  --memoh-root "$MEMOH_ROOT"
chmod 600 "$MEMOH_ROOT/.env.memoh" 2>/dev/null || true

echo "=== Memoh: build + up ==="
docker compose -f deploy/docker-compose.memoh.yml build
docker compose -f deploy/docker-compose.memoh.yml up -d

echo "=== wait Studio /health (up to ~140s) ==="
ok=0
for i in $(seq 1 70); do
  if curl -sf --max-time 5 "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    ok=1
    echo "STUDIO_HEALTH_OK iteration=$i"
    break
  fi
  sleep 2
done
test "$ok" = 1

echo "=== wait Memoh stack (web GET /health on 8082, up to ~140s) ==="
ok=0
for i in $(seq 1 70); do
  # Стабильнее, чем HEAD к API :8080 (curl с хоста иногда таймаутил).
  if curl -sf --max-time 5 -o /dev/null "http://127.0.0.1:8082/health" 2>/dev/null; then
    ok=1
    echo "MEMOH_HEALTH_OK iteration=$i"
    break
  fi
  sleep 2
done
test "$ok" = 1

echo "=== post-Memoh API settle ==="
sleep 12

echo "=== sync Memoh admin password (DB) from config.toml ==="
if ! python3 -c "import bcrypt" 2>/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get update -qq && apt-get install -y python3-bcrypt >/dev/null
fi
python3 deploy/scripts/memoh_sync_admin_db_password.py

echo "=== Telegram webhook (Memoh) ==="
python3 deploy/scripts/memoh_delete_telegram_webhook.py --memoh-env "$MEMOH_ROOT/.env.memoh"
python3 deploy/scripts/memoh_bootstrap_telegram_channel.py --memoh-root "$MEMOH_ROOT"

if test -f deploy/caddy/Caddyfile.pb-web.ru; then
  echo "=== Caddy reload from repo ==="
  cp deploy/caddy/Caddyfile.pb-web.ru /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile
  caddy reload --config /etc/caddy/Caddyfile
fi

echo "=== e2e smoke ==="
REPO="$REPO" BASE="https://jar.pb-web.ru" bash ./deploy/scripts/vps-e2e-smoke.sh || echo "SMOKE_EXIT_$?"

echo "=== DEPLOY_ALL_DONE ==="
