#!/usr/bin/env bash
# Обёртка: валидация .env.prod через Python (без сторонних зависимостей).
#
# Usage:
#   ./deploy/scripts/validate-env-prod.sh
#   ./deploy/scripts/validate-env-prod.sh /path/to/.env.prod

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${1:-$ROOT/.env.prod}"
exec python3 "$ROOT/deploy/scripts/validate_env_prod.py" "$ENV_FILE"
