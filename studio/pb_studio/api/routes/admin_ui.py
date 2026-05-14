from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.templating import Jinja2Templates

from pb_studio.admin_ui import data as admin_data
from pb_studio.admin_ui import templates_dir
from pb_studio.admin_ui.auth import (
    COOKIE_NAME,
    issue_session_cookie,
    redirect_if_logged_in,
    require_admin_ui,
)
from pb_studio.api.deps import DbSession
from pb_studio.core.config import Settings, get_settings

templates = Jinja2Templates(directory=str(templates_dir()))

router = APIRouter(prefix="/admin", tags=["admin-ui"])

_admin_dep = [Depends(require_admin_ui)]


def _safe_token_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return False


@router.get("/login", response_class=HTMLResponse)
async def admin_login_get(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    next_path: str | None = Query(None, alias="next"),
) -> Response:
    redir = redirect_if_logged_in(request, settings)
    if redir:
        return redir
    token_ok = bool((settings.studio_admin_token or "").strip())
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "not_configured": not token_ok,
            "error": None,
            "next_url": next_path or "",
        },
    )


@router.post("/login")
async def admin_login_post(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    admin_token: str = Form(...),
    next: str = Form(""),
) -> Response:
    expected = (settings.studio_admin_token or "").strip()
    if not expected or not _safe_token_eq(admin_token.strip(), expected):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "not_configured": False,
                "error": "Неверный токен",
                "next_url": next or "",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    dest = (next or "").strip() or "/admin/"
    if not dest.startswith("/admin"):
        dest = "/admin/"
    resp = RedirectResponse(url=dest, status_code=status.HTTP_302_FOUND)
    val = issue_session_cookie(settings)
    resp.set_cookie(
        COOKIE_NAME,
        val,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
        path="/admin",
    )
    return resp


@router.post("/logout", dependencies=_admin_dep)
async def admin_logout() -> RedirectResponse:
    resp = RedirectResponse("/admin/login", status_code=status.HTTP_302_FOUND)
    resp.delete_cookie(COOKIE_NAME, path="/admin")
    return resp


@router.get("/", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_dashboard(request: Request, session: DbSession) -> HTMLResponse:
    counts = await admin_data.fetch_dashboard_counts(session)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"nav_active": "dashboard", "counts": counts},
    )


def _table(
    request: Request,
    *,
    nav: str,
    title: str,
    subtitle: str,
    columns: list[str],
    rows: list[list[str]],
) -> HTMLResponse:
    empty = len(rows) == 0
    return templates.TemplateResponse(
        request,
        "table_page.html",
        {
            "nav_active": nav,
            "page_title": title,
            "page_subtitle": subtitle,
            "columns": columns,
            "rows": rows,
            "empty": empty,
        },
    )


@router.get("/chats", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_chats(request: Request, session: DbSession) -> HTMLResponse:
    rows_db = await admin_data.list_chats(session)
    rows = [[str(c.id), str(c.telegram_chat_id), c.chat_type or "", (c.title or "")[:80], c.chat_role] for c in rows_db]
    return _table(
        request,
        nav="chats",
        title="Чаты",
        subtitle="studio_chats (последние 50)",
        columns=["id", "telegram_chat_id", "type", "title", "chat_role"],
        rows=rows,
    )


@router.get("/control-group", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_control_group(request: Request, session: DbSession) -> HTMLResponse:
    view = await admin_data.fetch_control_group_view(session)
    if not view:
        return _table(
            request,
            nav="cg",
            title="Control group",
            subtitle="Активная запись не найдена",
            columns=["—"],
            rows=[],
        )
    cg = view["control_group"]
    ch = view["chat"]
    rows = [[str(cg.id), str(ch.telegram_chat_id), ch.title or "", str(cg.is_active), str(cg.created_at)]]
    return _table(
        request,
        nav="cg",
        title="Control group",
        subtitle="Активная studio_control_groups + чат",
        columns=["cg_id", "telegram_chat_id", "title", "is_active", "created_at"],
        rows=rows,
    )


@router.get("/summaries", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_summaries(request: Request, session: DbSession) -> HTMLResponse:
    items = await admin_data.list_summaries(session)
    rows = [
        [str(s.id), str(s.chat_id), s.summary_type, s.status, str(s.period_start), str(s.period_end)]
        for s in items
    ]
    return _table(
        request,
        nav="summaries",
        title="Сводки",
        subtitle="studio_chat_summaries (последние 50)",
        columns=["id", "chat_id", "type", "status", "period_start", "period_end"],
        rows=rows,
    )


@router.get("/projects", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_projects(request: Request, session: DbSession) -> HTMLResponse:
    items = await admin_data.list_projects(session)
    rows = [[str(p.id), p.slug, p.name, str(p.created_at)] for p in items]
    return _table(
        request,
        nav="projects",
        title="Проекты",
        subtitle="studio_projects",
        columns=["id", "slug", "name", "created_at"],
        rows=rows,
    )


@router.get("/sla/incidents", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_sla_incidents(request: Request, session: DbSession) -> HTMLResponse:
    items = await admin_data.list_sla_incidents(session)
    rows = [
        [str(i.id), str(i.chat_id), i.status, i.severity, str(i.due_at), str(i.created_at)] for i in items
    ]
    return _table(
        request,
        nav="sla",
        title="SLA инциденты",
        subtitle="studio_sla_incidents",
        columns=["id", "chat_id", "status", "severity", "due_at", "created_at"],
        rows=rows,
    )


@router.get("/knowledge/documents", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_kb_documents(request: Request, session: DbSession) -> HTMLResponse:
    items = await admin_data.list_knowledge_documents(session)
    rows = [[str(d.id), d.title, d.status, str(d.project_id or ""), str(d.created_at)] for d in items]
    return _table(
        request,
        nav="kb",
        title="KB документы",
        subtitle="studio_knowledge_documents",
        columns=["id", "title", "status", "project_id", "created_at"],
        rows=rows,
    )


@router.get("/assistant-rules", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_assistant_rules(request: Request, session: DbSession) -> HTMLResponse:
    items = await admin_data.list_assistant_rules(session)
    rows = [
        [str(r.id), r.scope, r.status, (r.rule_text or "")[:120], str(r.project_id or ""), str(r.chat_id or "")]
        for r in items
    ]
    return _table(
        request,
        nav="rules",
        title="Правила ассистента",
        subtitle="studio_assistant_rules",
        columns=["id", "scope", "status", "rule_text", "project_id", "chat_id"],
        rows=rows,
    )


@router.get("/history-import/jobs", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_history_jobs(request: Request, session: DbSession) -> HTMLResponse:
    items = await admin_data.list_history_import_jobs(session)
    rows = [
        [
            str(j.id),
            j.source_type,
            j.status,
            str(j.imported_chat_count),
            str(j.imported_message_count),
            str(j.skipped_count),
            (j.file_name or "")[:40],
        ]
        for j in items
    ]
    return _table(
        request,
        nav="hist",
        title="Импорт истории",
        subtitle="studio_history_import_jobs",
        columns=["id", "source", "status", "chats", "msgs", "skipped", "file"],
        rows=rows,
    )
