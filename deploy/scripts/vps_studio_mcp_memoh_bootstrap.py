#!/usr/bin/env python3
"""VPS-only bootstrap: STUDIO_MCP_AUTH_TOKEN, studio-mcp checks, Memoh MCP API, skill copy.
Does not print secrets, full .env, or tokens. Run on Linux host with docker."""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/pb-studio/pb-memoh-studio")
MEMOH_ROOT = Path("/opt/pb-studio/memoh")
ENVP = ROOT / ".env.prod"
COMPOSE = ["docker", "compose", "--env-file", str(ENVP), "-f", "docker-compose.prod.yml"]
SRV = "memoh-jar-server-1"
PG = "memoh-jar-postgres-1"


def run(cmd: list[str], *, cwd: Path | None = None, input_b: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, input=input_b, capture_output=True)


def main() -> int:
    if not ENVP.is_file():
        print("MISSING", ENVP)
        return 1

    text = ENVP.read_text(encoding="utf-8", errors="replace")

    def token_value() -> str:
        m = re.search(r"^STUDIO_MCP_AUTH_TOKEN=(.*)$", text, re.M)
        if not m:
            return ""
        return m.group(1).strip().strip('"').strip("'")

    if not token_value():
        tok = secrets.token_hex(32)
        if re.search(r"^STUDIO_MCP_AUTH_TOKEN=", text, re.M):
            text = re.sub(r"^STUDIO_MCP_AUTH_TOKEN=.*$", "STUDIO_MCP_AUTH_TOKEN=" + tok, text, count=1, flags=re.M)
        else:
            text = text.rstrip() + "\nSTUDIO_MCP_AUTH_TOKEN=" + tok + "\n"
        ENVP.write_text(text, encoding="utf-8")
        print("STUDIO_MCP_AUTH_TOKEN: filled_if_was_empty=yes")
    else:
        print("STUDIO_MCP_AUTH_TOKEN: already_set=yes")

    nl = run(["sh", "-lc", f"grep -E '^STUDIO_NL_COMMANDS_ENABLED=' {ENVP} 2>/dev/null | cut -d= -f2 | tr -d '\\n' || true"])
    print("STUDIO_NL_COMMANDS_ENABLED_value=", (nl.stdout or b"").decode().strip()[:20])

    r = run(COMPOSE + ["up", "-d", "studio-mcp"], cwd=ROOT)
    if r.returncode != 0:
        print("COMPOSE_UP_FAIL", r.returncode, (r.stderr or b"").decode()[-500:])
        return 1
    print("studio-mcp: compose_up=ok")

    chk = run(
        COMPOSE
        + [
            "exec",
            "-T",
            "studio-mcp",
            "python3",
            "-c",
            "import os,urllib.request,urllib.error\n"
            "tok=(os.environ.get('STUDIO_MCP_AUTH_TOKEN')or'').strip()\n"
            "paths=['http://127.0.0.1:8765/','http://127.0.0.1:8765/mcp']\n"
            "for p in paths:\n"
            " for mode in ('noauth','auth'):\n"
            "  req=urllib.request.Request(p)\n"
            "  if mode=='auth' and tok: req.add_header('Authorization','Bearer '+tok)\n"
            "  try:\n"
            "   r=urllib.request.urlopen(req,timeout=5);c=r.getcode()\n"
            "  except urllib.error.HTTPError as e: c=e.code\n"
            "  except Exception as e: c='err:'+type(e).__name__\n"
            "  print(p,mode,c)",
        ],
        cwd=ROOT,
    )
    sys.stdout.write((chk.stdout or b"").decode())
    if chk.returncode != 0:
        print("MCP_INNER_CHECK_FAIL", chk.returncode)
    r2 = run(["docker", "exec", SRV, "sh", "-lc", "getent hosts studio-mcp || true"])
    print("memoh_dns_studio_mcp:", (r2.stdout or b"").decode().strip()[:120])
    r3 = run(
        [
            "docker",
            "exec",
            SRV,
            "python3",
            "-c",
            "import urllib.request,urllib.error\n"
            "for p in ('http://studio-mcp:8765/','http://studio-mcp:8765/mcp'):\n"
            " try:\n"
            "  r=urllib.request.urlopen(urllib.request.Request(p),timeout=5)\n"
            "  print(p,'noauth',r.getcode())\n"
            " except urllib.error.HTTPError as e:\n"
            "  print(p,'noauth',e.code)\n"
            " except Exception as e:\n"
            "  print(p,'noauth_err',type(e).__name__)\n",
        ]
    )
    sys.stdout.write((r3.stdout or b"").decode())

    cfg_path = MEMOH_ROOT / "config.toml"
    if not cfg_path.is_file():
        print("MEMOH_CONFIG_MISSING")
        return 0

    cfg = cfg_path.read_text(encoding="utf-8", errors="replace")

    def toml_admin_field(field: str) -> str:
        in_admin = False
        for line in cfg.splitlines():
            s = line.strip()
            if s == "[admin]":
                in_admin = True
                continue
            if s.startswith("[") and s.endswith("]"):
                in_admin = False
                continue
            if not in_admin or "=" not in s:
                continue
            key, _, val = s.partition("=")
            if key.strip() != field:
                continue
            return val.strip().strip('"').strip("'")
        return ""

    user = toml_admin_field("username") or "admin"
    password = toml_admin_field("password")
    if not password:
        print("MEMOH_API_SKIP=no_admin_password")
        return 0

    login_body = json.dumps({"username": user, "password": password}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8080/auth/login",
        data=login_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            lr = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print("MEMOH_LOGIN_HTTP", e.code)
        return 0
    except Exception as e:
        print("MEMOH_LOGIN_ERR", type(e).__name__)
        return 0

    jwt = (lr.get("access_token") or "").strip()
    if not jwt:
        print("MEMOH_LOGIN_NO_TOKEN")
        return 0

    pg = run(
        [
            "docker",
            "exec",
            PG,
            "psql",
            "-U",
            "memoh",
            "-d",
            "memoh",
            "-t",
            "-A",
            "-c",
            "SELECT b.id::text FROM bots b "
            "LEFT JOIN bot_channel_configs c ON c.bot_id = b.id AND c.channel_type = 'telegram' "
            "WHERE COALESCE(b.display_name,'') ILIKE '%Purple%' "
            "OR COALESCE(b.display_name,'') ILIKE '%jarvis%' "
            "OR COALESCE(c.credentials::text,'') ILIKE '%jarvispbweb%' "
            "ORDER BY b.created_at DESC NULLS LAST LIMIT 1;",
        ]
    )
    bot_id = (pg.stdout or b"").decode().strip()
    if not bot_id:
        pg = run(
            [
                "docker",
                "exec",
                PG,
                "psql",
                "-U",
                "memoh",
                "-d",
                "memoh",
                "-t",
                "-A",
                "-c",
                "SELECT b.id::text FROM bots b "
                "WHERE COALESCE(b.display_name,'') NOT ILIKE '%studio bridge%' "
                "ORDER BY b.created_at DESC NULLS LAST LIMIT 1;",
            ]
        )
        bot_id = (pg.stdout or b"").decode().strip()
    if not bot_id:
        pg = run(
            [
                "docker",
                "exec",
                PG,
                "psql",
                "-U",
                "memoh",
                "-d",
                "memoh",
                "-t",
                "-A",
                "-c",
                "SELECT id::text FROM bots ORDER BY created_at DESC NULLS LAST LIMIT 1;",
            ]
        )
        bot_id = (pg.stdout or b"").decode().strip()
    if not bot_id:
        pg2 = run(
            [
                "docker",
                "exec",
                PG,
                "psql",
                "-U",
                "memoh",
                "-d",
                "memoh",
                "-t",
                "-A",
                "-c",
                "SELECT id::text, display_name FROM bots ORDER BY created_at DESC NULLS LAST LIMIT 8;",
            ]
        )
        print("BOT_NOT_FOUND_TRY_MANUAL")
        sys.stdout.write((pg2.stdout or b"").decode()[:500])
        print()
        return 0

    text = ENVP.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^STUDIO_MCP_AUTH_TOKEN=(.*)$", text, re.M)
    studio_tok = (m.group(1).strip().strip('"').strip("'") if m else "")

    def api(method: str, path: str, body: dict | None = None) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(
            "http://127.0.0.1:8080" + path,
            data=data,
            headers={
                "Authorization": "Bearer " + jwt,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return resp.getcode(), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    code, raw = api("GET", f"/bots/{bot_id}/mcp")
    if code != 200:
        print("MCP_LIST_FAIL", code)
        return 0
    items = json.loads(raw.decode()).get("items") or []
    conn_id = None
    for it in items:
        if (it.get("name") or "").strip() == "pb-studio-mcp":
            conn_id = (it.get("id") or "").strip()
            break

    base_urls = ["http://studio-mcp:8765/mcp", "http://studio-mcp:8765/"]

    def upsert_with_url(url: str) -> str:
        nonlocal conn_id
        body = {
            "name": "pb-studio-mcp",
            "url": url,
            "transport": "http",
            "headers": {"Authorization": "Bearer " + studio_tok},
            "is_active": True,
        }
        if conn_id:
            code_u, _ = api("PUT", f"/bots/{bot_id}/mcp/{conn_id}", body)
            print("MCP_UPSERT", "update", code_u, "url_hostpath=", url.split("://", 1)[-1][:40])
        else:
            code_u, cr = api("POST", f"/bots/{bot_id}/mcp", body)
            print("MCP_UPSERT", "create", code_u, "url_hostpath=", url.split("://", 1)[-1][:40])
            if code_u in (200, 201):
                try:
                    conn_id = (json.loads(cr.decode()).get("id") or "").strip()
                except Exception:
                    pass
        if not conn_id:
            code2, raw2 = api("GET", f"/bots/{bot_id}/mcp")
            if code2 == 200:
                for it in json.loads(raw2.decode()).get("items") or []:
                    if (it.get("name") or "").strip() == "pb-studio-mcp":
                        conn_id = (it.get("id") or "").strip()
                        break
        return conn_id or ""

    chosen = ""
    for candidate in base_urls:
        upsert_with_url(candidate)
        if not conn_id:
            continue
        pcode, praw = api("POST", f"/bots/{bot_id}/mcp/{conn_id}/probe")
        try:
            pr = json.loads(praw.decode())
        except Exception:
            pr = {}
        tools = pr.get("tools") or []
        names = [t.get("name", "") for t in tools if isinstance(t, dict)]
        studio_n = sum(1 for n in names if str(n).startswith("studio_"))
        print(
            "MCP_PROBE",
            pcode,
            "tools_total=",
            len(names),
            "studio_prefix=",
            studio_n,
            "status=",
            pr.get("status"),
            "url_tried=",
            candidate.split("://", 1)[-1][:48],
        )
        if studio_n >= 10:
            chosen = candidate
            break

    if not chosen and conn_id:
        print("MCP_PROBE_RETRY_NOTE=try alternate URL in UI if studio_prefix low")

    skill_src = ROOT / "skills" / "pb-studio-manager" / "SKILL.md"
    if skill_src.is_file():
        run(["docker", "exec", SRV, "sh", "-lc", "mkdir -p /data/skills/pb-studio-manager"])
        cp = run(["docker", "cp", str(skill_src), f"{SRV}:/data/skills/pb-studio-manager/SKILL.md"])
        print("SKILL_COPY", "ok" if cp.returncode == 0 else "fail", cp.returncode)
        st = run(["docker", "exec", SRV, "sh", "-lc", "test -s /data/skills/pb-studio-manager/SKILL.md && echo yes || echo no"])
        print("SKILL_PRESENT", (st.stdout or b"").decode().strip())
    else:
        print("SKILL_SRC_MISSING", skill_src)

    envm = run(
        [
            "docker",
            "exec",
            SRV,
            "sh",
            "-lc",
            "printf '%s,%s\\n' \"${MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED:-}\" \"${MEMOH_STUDIO_NL_GATE_DISABLED:-}\"",
        ]
    )
    print("MEMOH_FLAGS", (envm.stdout or b"").decode().strip()[:120])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
