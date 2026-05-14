#!/usr/bin/env python3
"""Merge key=value pairs from JSON into a dotenv file (replace existing keys). Does not print secret values."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: merge_env_json_into_dotenv.py /path/to/.env.prod /path/to/patch.json", file=sys.stderr)
        return 2
    envp = Path(sys.argv[1])
    patchp = Path(sys.argv[2])
    patch = json.loads(patchp.read_text(encoding="utf-8"))
    if not isinstance(patch, dict):
        print("patch must be a JSON object", file=sys.stderr)
        return 2
    keys = [str(k) for k in patch]
    lines = envp.read_text(encoding="utf-8").splitlines()

    def line_key(line: str) -> str | None:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            return None
        return s.split("=", 1)[0].strip()

    filtered = [ln for ln in lines if line_key(ln) not in keys]
    for k in keys:
        v = patch[k]
        filtered.append(f"{k}={v}")
    envp.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    os.chmod(envp, 0o600)
    print(f"merged {len(keys)} keys into {envp} (size {envp.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
