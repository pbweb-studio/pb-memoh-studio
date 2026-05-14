#!/usr/bin/env python3
"""
Логин в Memoh API, при необходимости создаёт бота, включает Telegram channel (bot_token).
Читает TELEGRAM_BOT_TOKEN из .env.memoh; пароль admin из config.toml [admin] password.
Ничего секретного в stdout не пишет.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path


def load_kv_env(path: Path, key: str) -> str:
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{key} not found in {path}")


def read_admin_password(toml_path: Path) -> tuple[str, str]:
    text = toml_path.read_text(encoding="utf-8", errors="replace")
    user_m = re.search(r'^\s*username\s*=\s*"([^"]*)"', text, re.MULTILINE)
    pass_m = re.search(r'^\s*password\s*=\s*"([^"]*)"', text, re.MULTILINE)
    if not user_m or not pass_m:
        raise SystemExit("could not parse [admin] username/password from config.toml")
    return user_m.group(1), pass_m.group(1)


def http_json(
    method: str,
    url: str,
    body: object | None,
    headers: dict[str, str],
    timeout: float = 60.0,
) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    hdrs = dict(headers)
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return e.code, parsed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080", help="Memoh HTTP API")
    ap.add_argument("--memoh-root", type=Path, required=True)
    args = ap.parse_args()

    memoh_root: Path = args.memoh_root
    env_file = memoh_root / ".env.memoh"
    cfg_file = memoh_root / "config.toml"
    bot_token = load_kv_env(env_file, "TELEGRAM_BOT_TOKEN")
    admin_user, admin_pass = read_admin_password(cfg_file)

    base = args.base_url.rstrip("/")

    status, login_body = http_json(
        "POST",
        f"{base}/auth/login",
        {"username": admin_user, "password": admin_pass},
        {},
    )
    if status != 200:
        raise SystemExit(f"login failed HTTP {status}: {login_body}")
    access = str(login_body.get("access_token", "")).strip()
    if not access:
        raise SystemExit("login: no access_token in response")

    auth = {"Authorization": f"Bearer {access}"}

    status, bots_body = http_json("GET", f"{base}/bots", None, auth)
    if status != 200:
        raise SystemExit(f"list bots failed HTTP {status}: {bots_body}")

    items = bots_body.get("items") if isinstance(bots_body, dict) else None
    if not isinstance(items, list):
        raise SystemExit("unexpected /bots response")

    bot_id: str | None = None
    if items:
        first = items[0]
        if isinstance(first, dict) and first.get("id"):
            bot_id = str(first["id"])

    if not bot_id:
        status, created = http_json("POST", f"{base}/bots", {"display_name": "Studio bridge"}, auth)
        if status not in (200, 201):
            raise SystemExit(f"create bot failed HTTP {status}: {created}")
        if not isinstance(created, dict) or not created.get("id"):
            raise SystemExit("create bot: unexpected response")
        bot_id = str(created["id"])
        print(f"OK: created bot id={bot_id}")
    else:
        print(f"OK: using existing bot id={bot_id}")

    status, ch = http_json(
        "PUT",
        f"{base}/bots/{bot_id}/channel/telegram",
        {"credentials": {"bot_token": bot_token}},
        auth,
        timeout=120.0,
    )
    if status != 200:
        raise SystemExit(f"upsert telegram channel failed HTTP {status}: {ch}")
    print("OK: telegram channel configured (token not printed)")


if __name__ == "__main__":
    main()
