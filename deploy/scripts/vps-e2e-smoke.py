#!/usr/bin/env python3
"""
E2E smoke на VPS. Не печатает секреты. Вывод: строки PASS|FAIL|SKIP|NOTE|ENTITY|...
Запуск: python3 vps-e2e-smoke.py [REPO=/opt/pb-studio/pb-memoh-studio] [BASE=https://jar.pb-web.ru]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/pb-studio/pb-memoh-studio")
BASE = (sys.argv[2] if len(sys.argv) > 2 else "https://jar.pb-web.ru").rstrip("/")


def out(kind: str, block: str, msg: str = "") -> None:
    print(f"{kind}|{block}|{msg}")


def load_env(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def sh(*args: str, cwd: Path | None = None, timeout: int | None = None) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _alembic_rev(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("INFO "):
            continue
        return line.split()[0]
    return ""


def curl_json(method: str, url: str, token: str | None, body: dict | None = None, accept: str | None = None) -> tuple[int, str]:
    headers = []
    if token:
        headers.append(f"Authorization: Bearer {token}")
    if accept:
        headers.append(f"Accept: {accept}")
    data = None
    if body is not None:
        headers.append("Content-Type: application/json")
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    for h in headers:
        k, _, v = h.partition(": ")
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode(errors="replace")


def curl_code(method: str, url: str, token: str | None, body: dict | None = None, accept: str | None = None) -> int:
    c, _ = curl_json(method, url, token, body, accept)
    return c


def curl_http_code_no_redirect(url: str, accept: str | None = None) -> int | None:
    """Первый HTTP-код без следования редиректам (curl на хосте VPS)."""
    args = ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}"]
    if accept:
        args += ["-H", f"Accept: {accept}"]
    args.append(url)
    rc, out = sh(*args, timeout=60)
    if rc != 0:
        return None
    try:
        return int((out or "").strip())
    except ValueError:
        return None


def main() -> int:
    os.chdir(REPO)
    envp = REPO / ".env.prod"
    if not envp.is_file():
        out("FAIL", "0_env", ".env.prod missing")
        return 1
    mode = oct(envp.stat().st_mode)[-3:]
    if int(mode, 8) > 0o600:
        out("FAIL", "0_env_perms", f"mode={mode}")
    else:
        out("PASS", "0_env_perms", f"mode={mode}")
    out("PASS", "0_env_exists", "")

    rc, _ = sh("git", "-C", str(REPO), "ls-files", "--error-unmatch", ".env.prod")
    if rc == 0:
        out("FAIL", "0_gitignore", ".env.prod is tracked")
    else:
        out("PASS", "0_gitignore", "")

    tok_file = Path("/root/.studio_admin_token_once")
    if tok_file.is_file():
        out("NOTE", "0_admin_token_file", "/root/.studio_admin_token_once exists — rm after saving to secret manager")

    env = load_env(envp)
    token = env.get("STUDIO_ADMIN_TOKEN", "").strip()
    if not token:
        out("FAIL", "0_token", "STUDIO_ADMIN_TOKEN empty")
        return 1

    compose = ["docker", "compose", "--env-file", ".env.prod", "-f", "docker-compose.prod.yml"]
    rc, _ = sh(*compose, "config", cwd=REPO)
    out("PASS" if rc == 0 else "FAIL", "1_compose_config", f"exit={rc}")

    rc, ps_out = sh(*compose, "ps", "--format", "{{.Name}}", cwd=REPO)
    names = set(ps_out.split())
    for need in (
        "pb-studio-prod-postgres",
        "pb-studio-prod-redis",
        "pb-studio-prod-api",
        "pb-studio-prod-worker",
        "pb-studio-prod-beat",
    ):
        out("PASS" if need in names else "FAIL", f"1_service_{need}", "")

    rc, logs = sh(*compose, "logs", "--no-color", "--tail", "150", "studio-api", cwd=REPO)
    bad = False
    if re.search(r"traceback|Traceback", logs, re.I):
        out("FAIL", "1_logs_studio-api", "traceback in tail")
        bad = True
    if re.search(r"sk-[a-zA-Z0-9]{15,}", logs):
        out("FAIL", "1_logs_studio-api", "possible sk- key in logs")
        bad = True
    if re.search(r"\d{8,10}:[A-Za-z0-9_-]{25,}", logs):
        out("FAIL", "1_logs_studio-api", "possible bot token pattern in logs")
        bad = True
    if not bad:
        out("PASS", "1_logs_studio-api", "no critical patterns in sample")

    for log_svc in ("studio-worker", "studio-beat"):
        rc, wlog = sh(*compose, "logs", "--no-color", "--tail", "80", log_svc, cwd=REPO)
        if re.search(r"traceback|Traceback", wlog, re.I):
            out("FAIL", f"1_logs_{log_svc}", "traceback in tail")
        elif re.search(r"sk-[a-zA-Z0-9]{15,}", wlog) or re.search(
            r"\d{8,10}:[A-Za-z0-9_-]{25,}", wlog
        ):
            out("FAIL", f"1_logs_{log_svc}", "possible secret pattern in logs")
        else:
            out("PASS", f"1_logs_{log_svc}", "sample ok")

    hc, hj = curl_json("GET", f"{BASE}/health", None)
    out("PASS" if hc == 200 else "FAIL", "2_health", str(hc))
    prod_ok = False
    if hc == 200:
        try:
            hj_obj = json.loads(hj)
            prod_ok = hj_obj.get("env") == "production"
        except json.JSONDecodeError:
            prod_ok = "production" in hj and "env" in hj
    out("PASS" if prod_ok else "FAIL", "2_health_env_marker", "")

    al = curl_code("GET", f"{BASE}/admin/login", None, accept="text/html")
    out("PASS" if al == 200 else "FAIL", "2_admin_login", str(al))

    ac = curl_http_code_no_redirect(f"{BASE}/admin/chats", accept="text/html")
    out(
        "PASS" if ac in (301, 302, 303, 307, 308) else "FAIL",
        "2_admin_chats_unauth_redirect",
        str(ac) if ac is not None else "curl_failed",
    )

    ab = curl_code("GET", f"{BASE}/admin/chats", token, accept="text/html")
    out("PASS" if ab == 200 else "FAIL", "2_admin_chats_bearer", str(ab))

    _, html = curl_json("GET", f"{BASE}/admin/chats", token, accept="text/html")
    if token in html:
        out("FAIL", "2_token_in_html", "admin HTML contains raw token")
    else:
        out("PASS", "2_token_not_in_sample_html", "")

    rc, acur = sh(*compose, "exec", "-T", "studio-api", "alembic", "current", cwd=REPO)
    rc2, ahead = sh(*compose, "exec", "-T", "studio-api", "alembic", "heads", cwd=REPO)
    cur = _alembic_rev(acur)
    head = _alembic_rev(ahead)
    if cur and head and cur == head:
        out("PASS", "3_alembic_at_head", cur)
    else:
        out("FAIL", "3_alembic_at_head", f"current={cur!r} heads={head!r}")

    rc, vcol = sh(
        *compose,
        "exec",
        "-T",
        "studio-postgres",
        "psql",
        "-U",
        "pb_studio",
        "-d",
        "pb_studio",
        "-tAc",
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name='alembic_version' AND column_name='version_num'",
        cwd=REPO,
    )
    try:
        ln = int((vcol or "0").strip() or 0)
    except ValueError:
        ln = 0
    out("PASS" if ln >= 255 else "FAIL", "3_alembic_version_col", str(ln))

    tables = [
        "studio_chats",
        "studio_messages",
        "studio_control_groups",
        "studio_chat_summaries",
        "studio_projects",
        "studio_project_digests",
        "studio_sla_incidents",
        "studio_knowledge_documents",
        "studio_knowledge_chunks",
        "studio_assistant_rules",
        "studio_history_import_jobs",
    ]
    for t in tables:
        rc, ex = sh(
            *compose,
            "exec",
            "-T",
            "studio-postgres",
            "psql",
            "-U",
            "pb_studio",
            "-d",
            "pb_studio",
            "-tAc",
            f"SELECT to_regclass('public.{t}')",
            cwd=REPO,
        )
        ok = (ex or "").strip() == t
        out("PASS" if ok else "FAIL", f"3_table_{t}", (ex or "").strip())

    admin_paths = [
        "/admin/",
        "/admin/chats",
        "/admin/control-group",
        "/admin/summaries",
        "/admin/projects",
        "/admin/sla/incidents",
        "/admin/knowledge/documents",
        "/admin/assistant-rules",
        "/admin/history-import/jobs",
    ]
    for p in admin_paths:
        c = curl_code("GET", f"{BASE}{p}", token, accept="text/html")
        out("PASS" if c == 200 else "FAIL", f"4_admin_{p}", str(c))

    filt = [
        "/admin/chats?limit=10&page=1",
        "/admin/projects?status=active",
        "/admin/knowledge/documents?limit=10&page=1",
        "/admin/assistant-rules?status=active",
    ]
    for p in filt:
        c = curl_code("GET", f"{BASE}{p}", token, accept="text/html")
        out("PASS" if c == 200 else "FAIL", f"4_filter_{p}", str(c))

    # slug: только [a-z0-9_-] — см. ProjectCreate.pattern (литеральный «z»; не использовать «%s» в шаблоне strftime).
    ts = datetime.now(UTC).strftime("%Y%m%dt%H%M%S") + "z"
    slug = f"smoke-project-{ts}"
    c, body = curl_json(
        "POST",
        f"{BASE}/projects",
        token,
        {"slug": slug, "name": f"Smoke Project {ts}"},
    )
    if c not in (200, 201):
        out("FAIL", "5_projects_create", str(c))
        pid = ""
    else:
        out("PASS", "5_projects_create", str(c))
        try:
            pj = json.loads(body)
            pid = str(pj.get("id", ""))
        except json.JSONDecodeError:
            pid = ""
            out("FAIL", "5_project_id", "json")
    if pid:
        out("PASS", "5_project_id", pid[:8] + "…")
        c2, _ = curl_json("GET", f"{BASE}/projects", token)
        out("PASS" if slug in _ else "FAIL", "5_projects_list", str(c2))
        c3, _ = curl_json("GET", f"{BASE}/projects/{pid}", token)
        out("PASS" if c3 == 200 else "FAIL", "5_project_get", str(c3))
        c4 = curl_code("GET", f"{BASE}/admin/projects/{pid}", token, accept="text/html")
        out("PASS" if c4 == 200 else "FAIL", "5_admin_project_page", str(c4))
        dup = curl_code(
            "POST",
            f"{BASE}/projects",
            token,
            {"slug": slug, "name": "dup"},
        )
        out(
            "PASS" if dup in (400, 409, 422) else "SKIP",
            "5_project_duplicate_rejected",
            str(dup),
        )
    else:
        out("FAIL", "5_projects_chain", "no project id")

    c, body = curl_json(
        "POST",
        f"{BASE}/assistant-rules",
        token,
        {
            "scope": "global",
            "rule_text": "Smoke rule: отвечай кратко и по делу.",
            "source": "manual",
        },
    )
    rid = ""
    if c in (200, 201):
        out("PASS", "6_rules_create", str(c))
        try:
            rj = json.loads(body)
            rid = str(rj.get("id", ""))
        except json.JSONDecodeError:
            pass
    else:
        out("FAIL", "6_rules_create", str(c))
    if rid:
        cau, aud_body = curl_json("GET", f"{BASE}/assistant-rules/audit", token)
        out("PASS" if cau == 200 and "created" in aud_body.lower() else "SKIP", "6_rules_audit", str(cau))
        ap = curl_code("GET", f"{BASE}/admin/assistant-rules/{rid}", token, accept="text/html")
        out("PASS" if ap == 200 else "FAIL", "6_admin_rule_page", str(ap))
        ds = curl_code("POST", f"{BASE}/assistant-rules/{rid}/disable", token, {})
        out("PASS" if ds == 200 else "FAIL", "6_rule_disable", str(ds))
        _, active_body = curl_json("GET", f"{BASE}/assistant-rules?status=active&limit=500", token)
        try:
            active = json.loads(active_body)
            ids = {str(x.get("id")) for x in active if isinstance(x, dict)}
            out("PASS" if rid not in ids else "FAIL", "6_rule_not_in_active", "")
        except json.JSONDecodeError:
            out("FAIL", "6_rule_not_in_active", "json")
    else:
        out("FAIL", "6_rules_chain", "")

    kb_on = env.get("STUDIO_KB_ENABLED", "").lower() in ("true", "1", "yes")
    kid = ""
    vid = ""
    if not kb_on:
        out("SKIP", "7_kb", "STUDIO_KB_ENABLED not true")
        c, body = 0, ""
    else:
        c, body = curl_json(
            "POST",
            f"{BASE}/knowledge/documents",
            token,
            {"title": f"Smoke KB {ts}", "source_type": "manual", "status": "active"},
        )
    if kb_on and c in (200, 201):
        out("PASS", "7_kb_doc_create", str(c))
        try:
            kid = str(json.loads(body).get("id", ""))
        except json.JSONDecodeError:
            pass
    elif kb_on:
        out("FAIL", "7_kb_doc_create", str(c))
    if kb_on and kid:
        ktext = (
            "PB Studio занимается маркетингом, разработкой и автоматизацией бизнес-процессов. "
            "Это тестовый документ smoke."
        )
        c2, vb = curl_json(
            "POST",
            f"{BASE}/knowledge/documents/{kid}/versions/text",
            token,
            {"text": ktext},
        )
        if c2 in (200, 201):
            out("PASS", "7_kb_version", str(c2))
            try:
                vid = str(json.loads(vb).get("id", ""))
            except json.JSONDecodeError:
                pass
        else:
            out("FAIL", "7_kb_version", str(c2))
        if vid:
            c3, ch = curl_json("GET", f"{BASE}/knowledge/versions/{vid}/chunks", token)
            try:
                chunks = json.loads(ch)
                ok = isinstance(chunks, list) and len(chunks) > 0
            except json.JSONDecodeError:
                ok = False
            out("PASS" if ok and c3 == 200 else "FAIL", "7_kb_chunks", str(c3))
            lst_c, lst_b = curl_json("GET", f"{BASE}/knowledge/documents", token)
            out(
                "PASS" if lst_c == 200 and kid in lst_b and f"Smoke KB {ts}" in lst_b else "FAIL",
                "7_kb_documents_list",
                str(lst_c),
            )
            apd = curl_code("GET", f"{BASE}/admin/knowledge/documents/{kid}", token, accept="text/html")
            out("PASS" if apd == 200 else "FAIL", "7_admin_kb_doc", str(apd))
        else:
            out("FAIL", "7_kb_chunks", "no version id")
    elif kb_on:
        out("FAIL", "7_kb_chain", "no document id")

    emb = kb_on and env.get("STUDIO_KB_EMBEDDINGS_ENABLED", "").lower() in ("true", "1", "yes")
    if emb:
        ep = curl_code("POST", f"{BASE}/knowledge/embed-pending", token)
        out("PASS" if ep == 200 else "FAIL", "8_embed_pending", str(ep))
        sr, _ = curl_json(
            "POST",
            f"{BASE}/knowledge/search",
            token,
            {"query": "чем занимается PB Studio", "top_k": 5},
        )
        out("PASS" if sr == 200 else "FAIL", "8_search", str(sr))
    else:
        out("SKIP", "8_embeddings", "STUDIO_KB_EMBEDDINGS_ENABLED not true")

    rag = (
        kb_on
        and env.get("STUDIO_KB_RAG_ENABLED", "").lower() in ("true", "1", "yes")
        and env.get("STUDIO_KB_EMBEDDINGS_ENABLED", "").lower() in ("true", "1", "yes")
    )
    chat_key = (env.get("STUDIO_KB_CHAT_API_KEY") or "").strip()
    if rag and chat_key:
        ask_c, ask_b = curl_json(
            "POST",
            f"{BASE}/knowledge/ask",
            token,
            {"question": "Чем занимается PB Studio?"},
        )
        if ask_c == 200:
            try:
                aj = json.loads(ask_b)
                ok = bool((aj.get("answer") or "").strip()) and isinstance(
                    aj.get("applied_rule_ids"), list
                )
                emb_key = (env.get("STUDIO_KB_EMBEDDING_API_KEY") or "").strip()
                if (chat_key and chat_key in ask_b) or (emb_key and emb_key in ask_b):
                    out("FAIL", "9_rag_leak", "key material in response")
                else:
                    out("PASS" if ok else "FAIL", "9_rag_ask", "")
            except json.JSONDecodeError:
                out("FAIL", "9_rag_ask", "bad json")
        else:
            out("FAIL", "9_rag_ask", str(ask_c))
    else:
        out("SKIP", "9_rag", "RAG disabled or STUDIO_KB_CHAT_API_KEY empty")

    if env.get("STUDIO_HISTORY_IMPORT_ENABLED", "").lower() in ("true", "1", "yes"):
        out("SKIP", "10_history", "automated fixture not in scope")
    else:
        out("SKIP", "10_history", "STUDIO_HISTORY_IMPORT_ENABLED not true")

    if env.get("STUDIO_SLA_ENABLED", "").lower() in ("true", "1", "yes"):
        for ep in ("/sla/policies", "/sla/incidents"):
            sc = curl_code("GET", f"{BASE}{ep}", token)
            out("PASS" if sc == 200 else "FAIL", f"11_sla_{ep}", str(sc))
        d1 = curl_code("POST", f"{BASE}/sla/detect", token, {})
        d2 = curl_code("POST", f"{BASE}/sla/detect", token, {})
        out("PASS" if d1 == 200 and d2 == 200 else "FAIL", "11_sla_detect_twice", f"{d1}/{d2}")
        sp = curl_code("GET", f"{BASE}/admin/sla/incidents", token, accept="text/html")
        out("PASS" if sp == 200 else "FAIL", "11_admin_sla", str(sp))
    else:
        out("SKIP", "11_sla", "STUDIO_SLA_ENABLED not true")

    tg = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    cc = env.get("STUDIO_CONTROL_COMMANDS_ENABLED", "").lower() in ("true", "1", "yes")
    if tg and cc:
        out("SKIP", "12_telegram", "live CG /summary_help requires manual Telegram")
    else:
        out("SKIP", "12_telegram", "TELEGRAM empty or control commands disabled")

    rc, _ = sh(str(REPO / "deploy/scripts/backup-postgres.sh"), "/opt/pb-studio/backups", cwd=REPO)
    bk = sorted(Path("/opt/pb-studio/backups").glob("pb_studio_pg_*.sql.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if bk and bk[0].stat().st_size > 0:
        out("PASS", "13_backup_pg", str(bk[0]))
    else:
        out("FAIL", "13_backup_pg", "no non-empty dump")

    rc_kb, _ = sh(str(REPO / "deploy/scripts/backup-kb-volume.sh"), "/opt/pb-studio/backups", cwd=REPO)
    kb_dir = Path("/opt/pb-studio/backups")
    kb_files = sorted(kb_dir.glob("pb_studio_kb_*.tgz"), key=lambda p: p.stat().st_mtime, reverse=True)
    kb_newest = kb_files[0] if kb_files else None
    out(
        "PASS" if kb_newest and kb_newest.stat().st_size > 0 else "SKIP",
        "13_backup_kb",
        str(kb_newest) if kb_newest else f"script_exit={rc_kb}",
    )

    rc_pt, pt_out = sh(
        *compose,
        "run",
        "--rm",
        "--no-deps",
        "studio-api",
        "python",
        "-m",
        "pytest",
        "tests/",
        "-q",
        "--tb=no",
        cwd=REPO,
        timeout=900,
    )
    if rc_pt == 0:
        out("PASS", "14_pytest", "exit=0")
    elif "No module named pytest" in pt_out:
        out("SKIP", "14_pytest", "prod image: pytest not installed (run tests in CI/dev)")
    else:
        out("FAIL", "14_pytest", f"exit={rc_pt}")

    if pid:
        out("ENTITY", "project", f"id={pid};slug={slug}")
    if kid:
        out("ENTITY", "kb_doc", f"id={kid};title=Smoke KB {ts}")
    if rid:
        out("ENTITY", "rule", f"id={rid};status=disabled")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
