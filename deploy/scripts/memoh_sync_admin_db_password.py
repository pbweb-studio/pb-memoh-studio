#!/usr/bin/env python3
"""
Синхронизирует пароль администратора Memoh в Postgres с секцией [admin] в config.toml.

Memoh создаёт пользователя только при пустой БД; смена password в toml не обновляет users.password_hash.
Требует: модуль Python bcrypt (например apt install python3-bcrypt); Docker с контейнером Postgres Memoh.

Секреты не печатаются (только факт успеха / число затронутых строк).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def read_admin_password(toml_path: Path) -> str:
    text = toml_path.read_text(encoding="utf-8", errors="replace")
    in_admin = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "[admin]":
            in_admin = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_admin = False
            continue
        if not in_admin:
            continue
        m = re.match(r'^password\s*=\s*"([^"]*)"', line)
        if m:
            return m.group(1)
    raise SystemExit("could not find [admin] password in memoh config.toml")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memoh-config", type=Path, default=Path("/opt/pb-studio/memoh/config.toml"))
    ap.add_argument(
        "--postgres-container",
        default="memoh-jar-postgres-1",
        help="docker container name for Memoh Postgres",
    )
    args = ap.parse_args()

    try:
        import bcrypt
    except ImportError:
        raise SystemExit("install bcrypt: apt-get install -y python3-bcrypt (or pip install bcrypt)")

    password = read_admin_password(args.memoh_config)
    if not password.strip():
        raise SystemExit("empty admin password in config")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    escaped = hashed.replace("'", "''")
    sql = f"UPDATE users SET password_hash = '{escaped}' WHERE username = 'admin';\n"

    proc = subprocess.run(
        ["docker", "exec", "-i", args.postgres_container, "psql", "-U", "memoh", "-d", "memoh"],
        input=sql.encode("utf-8"),
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"psql failed rc={proc.returncode}: {err}")
    out = proc.stdout.decode("utf-8", errors="replace")
    if "UPDATE 0" in out or out.rstrip().endswith("UPDATE 0"):
        raise SystemExit("UPDATE 0 rows (no user with username=admin?)")
    print("OK: admin password_hash synced from config.toml")


if __name__ == "__main__":
    main()
