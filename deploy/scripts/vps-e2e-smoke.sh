#!/usr/bin/env bash
# Делегирует на Python: без set -x, секреты не печатаются.
# На VPS: из корня репо с .env.prod:
#   REPO=/opt/pb-studio/pb-memoh-studio BASE=https://jar.pb-web.ru ./deploy/scripts/vps-e2e-smoke.sh
set -eu
REPO="${REPO:-/opt/pb-studio/pb-memoh-studio}"
BASE="${BASE:-https://jar.pb-web.ru}"
cd "$REPO"
exec python3 "$REPO/deploy/scripts/vps-e2e-smoke.py" "$REPO" "$BASE"
