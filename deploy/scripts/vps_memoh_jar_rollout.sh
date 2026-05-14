#!/usr/bin/env bash
# Раскатка Memoh + проверки на Jar-VPS. Без set -x, секреты не печатаются.
# Запуск на сервере: bash /path/to/vps_memoh_jar_rollout.sh
set -eu
set +x

REPO="${REPO:-/opt/pb-studio/pb-memoh-studio}"
MEMOH_ROOT="${MEMOH_ROOT:-/opt/pb-studio/memoh}"
STUDIO_BASE="${STUDIO_BASE:-http://127.0.0.1:8000}"

cd "$REPO"
echo "=== pwd ==="
pwd

echo "=== git status (porcelain) ==="
git status --porcelain=v1 || true

echo "=== HEAD (before fetch) ==="
git rev-parse HEAD

echo "=== docker ps (names) ==="
docker ps --format '{{.Names}}' | sort || true

echo "=== studio compose ps ==="
docker compose -f docker-compose.prod.yml ps || true

echo "=== .env.prod checks ==="
python3 - <<'PY'
from pathlib import Path
p = Path("/opt/pb-studio/pb-memoh-studio/.env.prod")
assert p.is_file(), "missing .env.prod"

def nonempty(key: str) -> bool:
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(key + "="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return len(v) > 0
    return False

print("TELEGRAM_BOT_TOKEN_nonempty", nonempty("TELEGRAM_BOT_TOKEN"))
print("STUDIO_EVENTS_INGEST_TOKEN_nonempty", nonempty("STUDIO_EVENTS_INGEST_TOKEN"))
PY

if git ls-files --error-unmatch .env.prod >/dev/null 2>&1; then
  echo "FAIL .env.prod must not be tracked by git"
  exit 1
fi
echo "OK .env.prod not in git index"

echo "=== git fetch + reset ==="
git fetch origin
git reset --hard origin/pb-studio/main

echo "=== HEAD (after reset) ==="
git rev-parse HEAD

test -f .env.prod && echo "OK .env.prod still present after reset"

echo "=== prepare Memoh runtime ==="
export MEMOH_ROOT
python3 deploy/scripts/prepare_memoh_runtime.py \
  --studio-env /opt/pb-studio/pb-memoh-studio/.env.prod \
  --memoh-root "$MEMOH_ROOT"

chmod 600 "$MEMOH_ROOT/.env.memoh" || true
test -f "$MEMOH_ROOT/config.toml" && echo "OK memoh config.toml"
test -d "$MEMOH_ROOT/providers" && echo "OK memoh providers dir"
test -f "$MEMOH_ROOT/.env.memoh" && echo "OK memoh .env.memoh"

echo "=== memoh compose up ==="
docker compose -f deploy/docker-compose.memoh.yml up -d

echo "=== memoh compose ps ==="
docker compose -f deploy/docker-compose.memoh.yml ps || true

echo "=== wait memoh API /health (up to ~120s) ==="
ok=0
for i in $(seq 1 60); do
  if curl -sf -o /dev/null -X HEAD "http://127.0.0.1:8080/health" 2>/dev/null; then
    ok=1
    echo "MEMOH_HEALTH_OK iteration=$i"
    break
  fi
  sleep 2
done
if [ "$ok" != 1 ]; then
  echo "FAIL memoh /health not ready"
  docker compose -f deploy/docker-compose.memoh.yml logs --tail=80 server 2>&1 | grep -viE 'token|password|secret|bearer|apikey' | tail -n 40 || true
  exit 1
fi

echo "=== delete Telegram webhook ==="
python3 deploy/scripts/memoh_delete_telegram_webhook.py --memoh-env "$MEMOH_ROOT/.env.memoh"

echo "=== bootstrap Telegram channel in Memoh ==="
python3 deploy/scripts/memoh_bootstrap_telegram_channel.py --memoh-root "$MEMOH_ROOT"

echo "=== getMe (no token printed) ==="
python3 - <<'PY'
import json
import urllib.request
from pathlib import Path

def token():
    p = Path("/opt/pb-studio/memoh/.env.memoh")
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no TELEGRAM_BOT_TOKEN in .env.memoh")

url = "https://api.telegram.org/bot" + token() + "/getMe"
with urllib.request.urlopen(url, timeout=30) as r:
    data = json.loads(r.read().decode("utf-8"))
print("getMe_ok", data.get("ok"))
res = data.get("result") or {}
print("bot_id", res.get("id"))
print("username", res.get("username"))
PY

echo "=== Event mirror env sanity (no values) ==="
python3 - <<'PY'
from pathlib import Path

def lines(p: Path):
    return p.read_text(encoding="utf-8", errors="replace").splitlines()

def has_kv(path: Path, key: str, expected: str | None = None) -> bool:
    for line in lines(path):
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k != key:
            continue
        if expected is None:
            return len(v) > 0
        return v == expected
    return False

m = Path("/opt/pb-studio/memoh/.env.memoh")
s = Path("/opt/pb-studio/pb-memoh-studio/.env.prod")

def ingest(p: Path) -> str:
    for line in lines(p):
        if line.startswith("STUDIO_EVENTS_INGEST_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

print("mirror_enabled", has_kv(m, "MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true"))
print("studio_events_url_ok", has_kv(m, "STUDIO_EVENTS_URL", "https://jar.pb-web.ru/events/telegram"))
im, is_ = ingest(m), ingest(s)
print("ingest_tokens_match", bool(im and is_ and im == is_))
PY

echo "=== studio-api logs: POST /events/telegram (last 250 lines) ==="
if docker compose -f docker-compose.prod.yml logs --tail=250 studio-api 2>&1 | grep -F "/events/telegram" | tail -n 5; then
  echo "LOG_HIT_events_telegram"
else
  echo "LOG_NO_HIT_events_telegram (send ping or /kb_help in Telegram, then re-check)"
fi

echo "=== DB counts (studio_chats / studio_messages) ==="
docker exec pb-studio-prod-postgres psql -U pb_studio -d pb_studio -t -A -c \
  "select 'chats='||count(*)::text from studio_chats;" 2>/dev/null || echo "DB_CHATS_COUNT_FAILED"

docker exec pb-studio-prod-postgres psql -U pb_studio -d pb_studio -t -A -c \
  "select 'messages='||count(*)::text from studio_messages;" 2>/dev/null || echo "DB_MSG_COUNT_FAILED"

echo "=== Try set control group (latest studio_chat by updated_at) ==="
python3 - <<PY
import json
import urllib.error
import urllib.request
from pathlib import Path

def load_env(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out

base = "${STUDIO_BASE}".rstrip("/")
env = load_env("/opt/pb-studio/pb-memoh-studio/.env.prod")
admin = env.get("STUDIO_ADMIN_TOKEN", "").strip()
headers: dict[str, str] = {}
if admin:
    headers["Authorization"] = "Bearer " + admin

def get_json(url: str):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

try:
    chats = get_json(base + "/chats")
except urllib.error.HTTPError as e:
    print("CHATS_HTTP", e.code)
    raise SystemExit(0)
except Exception as e:
    print("CHATS_ERR", type(e).__name__)
    raise SystemExit(0)

if not isinstance(chats, list) or not chats:
    print("NO_CHATS_SKIP_CONTROL_GROUP")
    raise SystemExit(0)

chats.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
tid = int(chats[0]["telegram_chat_id"])
body = json.dumps({"telegram_chat_id": tid}).encode("utf-8")
h2 = dict(headers)
h2["Content-Type"] = "application/json"
req = urllib.request.Request(base + "/control-group/set", data=body, headers=h2, method="POST")
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read().decode("utf-8"))
    print("CONTROL_GROUP_ACTIVE", out.get("active"))
except urllib.error.HTTPError as e:
    raw = e.read().decode("utf-8", errors="replace")
    print("CONTROL_GROUP_HTTP", e.code, raw[:200])
PY

echo "=== control-group GET ==="
python3 - <<PY
import json
import urllib.request
from pathlib import Path

def load_env(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out

base = "${STUDIO_BASE}".rstrip("/")
env = load_env("/opt/pb-studio/pb-memoh-studio/.env.prod")
admin = env.get("STUDIO_ADMIN_TOKEN", "").strip()
headers: dict[str, str] = {}
if admin:
    headers["Authorization"] = "Bearer " + admin
req = urllib.request.Request(base + "/control-group", headers=headers)
with urllib.request.urlopen(req, timeout=30) as r:
    out = json.loads(r.read().decode("utf-8"))
print("control_group_active", out.get("active"))
sc = out.get("studio_chat") or {}
if sc:
    print("cg_chat_telegram_id", sc.get("telegram_chat_id"))
    print("cg_chat_role", sc.get("chat_role"))
PY

echo "=== smoke ==="
REPO="$REPO" BASE="https://jar.pb-web.ru" bash ./deploy/scripts/vps-e2e-smoke.sh || echo "SMOKE_EXIT_$?"

echo "=== ROLLOUT_DONE ==="
