#!/usr/bin/env python3
"""Снимает webhook у бота (long polling в Memoh). Токен из .env.memoh TELEGRAM_BOT_TOKEN — не печатается."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def load_token(env_file: Path) -> str:
    for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("TELEGRAM_BOT_TOKEN not found in env file")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memoh-env", type=Path, required=True, help="Path to .env.memoh")
    args = ap.parse_args()

    token = load_token(args.memoh_env)
    url = f"https://api.telegram.org/bot{token}/deleteWebhook"
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"request failed: {e}") from e

    data = json.loads(body)
    if not data.get("ok"):
        raise SystemExit(f"Telegram API not ok: {data}")
    print("OK: deleteWebhook succeeded")


if __name__ == "__main__":
    main()
