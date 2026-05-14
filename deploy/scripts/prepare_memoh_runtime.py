#!/usr/bin/env python3
"""Готовит каталог Memoh рядом со Studio: config.toml, providers, .env.memoh (без вывода секретов)."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        raise SystemExit(f"missing file: {path}")
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--studio-env", type=Path, required=True, help="Путь к .env.prod Studio")
    p.add_argument("--memoh-root", type=Path, required=True, help="Каталог данных Memoh на хосте")
    args = p.parse_args()

    repo = args.repo_root
    studio_env = load_env(args.studio_env)
    memoh_root: Path = args.memoh_root
    memoh_root.mkdir(parents=True, exist_ok=True)

    src_toml = repo / "conf" / "app.docker.toml"
    if not src_toml.is_file():
        raise SystemExit(f"missing {src_toml}")
    shutil.copy2(src_toml, memoh_root / "config.toml")

    src_prov = repo / "conf" / "providers"
    dst_prov = memoh_root / "providers"
    if dst_prov.exists():
        shutil.rmtree(dst_prov)
    shutil.copytree(src_prov, dst_prov)

    token = studio_env.get("TELEGRAM_BOT_TOKEN", "").strip()
    ingest = studio_env.get("STUDIO_EVENTS_INGEST_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN missing in studio env")
    if not ingest:
        raise SystemExit("STUDIO_EVENTS_INGEST_TOKEN missing in studio env")

    lines = [
        "# Event mirror -> Studio (ingest token совпадает со Studio)",
        "MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED=true",
        "STUDIO_EVENTS_URL=https://jar.pb-web.ru/events/telegram",
        "MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS=8000",
        f"STUDIO_EVENTS_INGEST_TOKEN={ingest}",
        "",
        "# Для bootstrap/deleteWebhook (Memoh server читает токен из channel credentials, не из env)",
        f"TELEGRAM_BOT_TOKEN={token}",
        "",
        "TZ=UTC",
    ]
    (memoh_root / ".env.memoh").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"OK: wrote {memoh_root / 'config.toml'}")
    print(f"OK: wrote {memoh_root / '.env.memoh'} (secrets not printed)")
    print(f"OK: copied providers -> {dst_prov}")


if __name__ == "__main__":
    main()
