#!/usr/bin/env python3
"""
Настройка OpenAI provider + chat model для Memoh (устраняет «chat model not configured»).
Ключ берётся из Studio .env.prod: OPENAI_API_KEY, иначе STUDIO_KB_CHAT_API_KEY. Секреты не печатаются.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def read_admin_creds(toml_path: Path) -> tuple[str, str]:
    text = toml_path.read_text(encoding="utf-8", errors="replace")
    um = re.search(r'^\s*username\s*=\s*"([^"]*)"', text, re.MULTILINE)
    pm = re.search(r'^\s*password\s*=\s*"([^"]*)"', text, re.MULTILINE)
    if not um or not pm:
        raise SystemExit("could not parse [admin] from memoh config.toml")
    return um.group(1), pm.group(1)


def http_json(
    method: str,
    url: str,
    body: object | None,
    headers: dict[str, str],
    timeout: float = 30.0,
) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    hdrs = dict(headers)
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed: object = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {"detail": raw[:500]}
        return e.code, parsed


def resolve_chat_model_uuid(
    base: str, auth: dict[str, str], provider_id: str, chat_model: str
) -> str:
    """Memoh stores bots.chat_model_id as model row UUID; duplicate model_id across providers needs UUID."""
    status, models = http_json(
        "GET",
        f"{base}/providers/{provider_id}/models?type=chat",
        None,
        auth,
        timeout=60.0,
    )
    if status != 200:
        raise SystemExit(f"list provider models HTTP {status}: {models}")
    if not isinstance(models, list):
        raise SystemExit("unexpected /providers/.../models response")
    want = chat_model.strip()
    for m in models:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("model_id", "")).strip()
        mname = str(m.get("name", "")).strip()
        if mid == want or mname == want:
            uuid = str(m.get("id", "")).strip()
            if uuid:
                return uuid
    raise SystemExit(
        f"no chat model with model_id or name {want!r} under OpenAI provider; "
        f"provider has {len(models)} chat model(s)"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--studio-env", type=Path, required=True)
    ap.add_argument("--memoh-base", default="http://127.0.0.1:8080")
    ap.add_argument("--memoh-config", type=Path, default=Path("/opt/pb-studio/memoh/config.toml"))
    ap.add_argument("--chat-model", default="gpt-4o-mini")
    ap.add_argument("--bot-id", default="", help="optional; default first bot from GET /bots")
    args = ap.parse_args()

    studio = load_env(args.studio_env)
    api_key = (studio.get("OPENAI_API_KEY") or "").strip() or (studio.get("STUDIO_KB_CHAT_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("no OPENAI_API_KEY or STUDIO_KB_CHAT_API_KEY in studio env")

    admin_user, admin_pass = read_admin_creds(args.memoh_config)
    base = args.memoh_base.rstrip("/")

    status, login_body = http_json(
        "POST",
        f"{base}/auth/login",
        {"username": admin_user, "password": admin_pass},
        {},
    )
    if status != 200:
        raise SystemExit(f"login failed HTTP {status}")
    token = str(login_body.get("access_token", "")).strip()
    if not token:
        raise SystemExit("login: no access_token")
    auth = {"Authorization": f"Bearer {token}"}

    status, providers = http_json("GET", f"{base}/providers", None, auth)
    if status != 200:
        raise SystemExit(f"list providers HTTP {status}")
    if not isinstance(providers, list):
        raise SystemExit("unexpected /providers response")

    provider_id: str | None = None
    for p in providers:
        if not isinstance(p, dict):
            continue
        if str(p.get("client_type", "")).strip() == "openai-responses":
            provider_id = str(p.get("id", "")).strip()
            if provider_id:
                break

    if not provider_id:
        status, created = http_json(
            "POST",
            f"{base}/providers",
            {
                "name": "OpenAI",
                "client_type": "openai-responses",
                "icon": "openai",
                "config": {"api_key": api_key, "base_url": "https://api.openai.com/v1"},
            },
            auth,
        )
        if status not in (200, 201):
            raise SystemExit(f"create provider HTTP {status}: {created}")
        if not isinstance(created, dict) or not created.get("id"):
            raise SystemExit("create provider: bad response")
        provider_id = str(created["id"])
        print("OK: created OpenAI provider")
    else:
        status, _upd = http_json(
            "PUT",
            f"{base}/providers/{provider_id}",
            {"config": {"api_key": api_key, "base_url": "https://api.openai.com/v1"}},
            auth,
        )
        if status != 200:
            raise SystemExit(f"update provider HTTP {status}: {_upd}")
        print("OK: updated OpenAI provider api_key (value not printed)")

    status, imp = http_json("POST", f"{base}/providers/{provider_id}/import-models", {}, auth, timeout=60.0)
    if status != 200:
        print("WARN: import-models HTTP", status, str(imp)[:200])
    elif isinstance(imp, dict):
        print("OK: import-models created=", imp.get("created"), "skipped=", imp.get("skipped"))
    else:
        print("OK: import-models done")

    status, _gm = http_json("GET", f"{base}/models/model/{args.chat_model}", None, auth)
    if status != 200:
        status2, mbody = http_json(
            "POST",
            f"{base}/models",
            {
                "model_id": args.chat_model,
                "name": args.chat_model,
                "provider_id": provider_id,
                "type": "chat",
                "config": {
                    "compatibilities": ["vision", "tool-call"],
                    "context_window": 128000,
                },
            },
            auth,
        )
        if status2 not in (200, 201):
            if status2 == 409:
                print("OK: chat model already exists (409)")
            else:
                raise SystemExit(f"model missing and create failed HTTP {status2}: {mbody}")
        else:
            print("OK: registered chat model via POST /models (fallback)")
    else:
        print("OK: chat model present:", args.chat_model)

    bot_id = args.bot_id.strip()
    if not bot_id:
        status, bots_body = http_json("GET", f"{base}/bots", None, auth)
        if status != 200:
            raise SystemExit(f"list bots HTTP {status}")
        items = bots_body.get("items") if isinstance(bots_body, dict) else None
        if not items or not isinstance(items, list) or not items[0].get("id"):
            raise SystemExit("no bots found")
        bot_id = str(items[0]["id"])

    chat_uuid = resolve_chat_model_uuid(base, auth, provider_id, args.chat_model)
    status, st = http_json(
        "PUT",
        f"{base}/bots/{bot_id}/settings",
        {"chat_model_id": chat_uuid},
        auth,
    )
    if status != 200:
        raise SystemExit(f"put bot settings HTTP {status}: {st}")
    print("OK: bot chat model set", args.chat_model, "bot_id=", bot_id)


if __name__ == "__main__":
    main()
