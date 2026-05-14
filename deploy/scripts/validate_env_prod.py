#!/usr/bin/env python3
"""
Проверка .env.prod перед запуском: обязательные переменные, условные зависимости feature flags.
Не печатает значения секретов — только имена переменных и «set» / «unset» / «invalid placeholder».

Usage:
  python3 deploy/scripts/validate_env_prod.py
  python3 deploy/scripts/validate_env_prod.py /path/to/.env.prod

Exit code: 0 если ок, 1 при ошибках.
"""
from __future__ import annotations

import sys
from pathlib import Path

FORBIDDEN_SUBSTRINGS = (
    "CHANGE_ME_STRONG_POSTGRES_PASSWORD",
    "pb_studio_dev",  # дефолт dev из compose — не для реального prod
)

# Имена переменных, значения которых никогда не выводим
_SECRET_KEYS = frozenset(
    k.upper()
    for k in (
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "STUDIO_ADMIN_TOKEN",
        "STUDIO_EVENTS_INGEST_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "CELERY_RESULT_BACKEND",
        "STUDIO_KB_EMBEDDING_API_KEY",
        "STUDIO_KB_CHAT_API_KEY",
        "OPENAI_API_KEY",
    )
)


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        out[key] = val
    return out


def _status(key: str, val: str) -> str:
    if not val:
        return "unset"
    if key.upper() in _SECRET_KEYS:
        return "set"
    return "set"


def _invalid_placeholder(val: str) -> bool:
    if not val:
        return True
    for sub in FORBIDDEN_SUBSTRINGS:
        if sub in val:
            return True
    return False


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    env_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / ".env.prod"
    if not env_path.is_file():
        print(f"ERROR: file not found: {env_path}", file=sys.stderr)
        return 1

    env = _load_env(env_path)
    errors: list[str] = []

    def require(name: str) -> None:
        val = env.get(name, "")
        if not val.strip():
            errors.append(f"REQUIRED unset or empty: {name}")
            print(f"{name}: unset")
            return
        st = _status(name, val)
        print(f"{name}: {st}")
        if _invalid_placeholder(val):
            errors.append(f"REQUIRED invalid or placeholder value: {name} (change defaults / CHANGE_ME)")

    print(f"Validating (secrets hidden): {env_path}")
    print("--- REQUIRED (core prod) ---")
    require("POSTGRES_PASSWORD")
    require("DATABASE_URL")
    require("STUDIO_ADMIN_TOKEN")

    print("--- CONDITIONAL (feature flags) ---")
    telegram_needed = False
    if _truthy(env.get("STUDIO_SYSTEM_NOTIFICATIONS_ENABLED", "")):
        telegram_needed = True
        print("STUDIO_SYSTEM_NOTIFICATIONS_ENABLED=true → TELEGRAM_BOT_TOKEN required")
    if _truthy(env.get("STUDIO_SUMMARY_DELIVERY_ENABLED", "")):
        telegram_needed = True
        print("STUDIO_SUMMARY_DELIVERY_ENABLED=true → TELEGRAM_BOT_TOKEN required")
    if _truthy(env.get("STUDIO_KB_TELEGRAM_IMPORT_ENABLED", "")):
        telegram_needed = True
        print("STUDIO_KB_TELEGRAM_IMPORT_ENABLED=true → TELEGRAM_BOT_TOKEN required")

    if telegram_needed:
        t = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        print(f"TELEGRAM_BOT_TOKEN: {'set' if t else 'unset'}")
        if not t:
            errors.append("TELEGRAM_BOT_TOKEN required for enabled Telegram outbound / KB Telegram import")

    if _truthy(env.get("STUDIO_KB_EMBEDDINGS_ENABLED", "")):
        provider = env.get("STUDIO_KB_EMBEDDING_PROVIDER", "").strip().lower()
        if provider == "openai_compatible":
            base = env.get("STUDIO_KB_EMBEDDING_API_BASE_URL", "").strip()
            key = env.get("STUDIO_KB_EMBEDDING_API_KEY", "").strip()
            print("STUDIO_KB_EMBEDDINGS_ENABLED + openai_compatible → embedding API URL/key")
            if not base:
                errors.append("STUDIO_KB_EMBEDDING_API_BASE_URL required for openai_compatible embeddings")
            if not key:
                errors.append("STUDIO_KB_EMBEDDING_API_KEY required for openai_compatible embeddings")
            print(f"STUDIO_KB_EMBEDDING_API_BASE_URL: {'set' if base else 'unset'}")
            print(f"STUDIO_KB_EMBEDDING_API_KEY: {'set' if key else 'unset'}")

    if _truthy(env.get("STUDIO_KB_RAG_ENABLED", "")):
        print("STUDIO_KB_RAG_ENABLED=true → STUDIO_KB_CHAT_API_BASE_URL / KEY / MODEL")
        for key in ("STUDIO_KB_CHAT_API_BASE_URL", "STUDIO_KB_CHAT_API_KEY", "STUDIO_KB_CHAT_MODEL"):
            v = env.get(key, "").strip()
            print(f"{key}: {'set' if v else 'unset'}")
            if not v:
                errors.append(f"{key} required when STUDIO_KB_RAG_ENABLED=true")

    if errors:
        print("--- RESULT: FAIL ---", file=sys.stderr)
        for msg in errors:
            print(msg, file=sys.stderr)
        return 1

    print("--- RESULT: OK ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
