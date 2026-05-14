from __future__ import annotations

import hmac
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from starlette.templating import Jinja2Templates

from pb_studio.admin_ui import data as admin_data
from pb_studio.admin_ui import templates_dir
from pb_studio.admin_ui.formatting import format_admin_dt, snip_text
from pb_studio.admin_ui.pagination import (
    PaginationUrls,
    build_pagination_urls,
    clamp_limit,
    clamp_page,
    effective_page,
    offset_for,
)
from pb_studio.admin_ui.auth import (
    COOKIE_NAME,
    issue_session_cookie,
    redirect_if_logged_in,
    require_admin_ui,
)
from pb_studio.admin_ui.flash import redirect_with_flash
from pb_studio.api.deps import DbSession
from pb_studio.assistant_rules import service as rules_service
from pb_studio.assistant_rules.constants import AssistantRuleScope, AssistantRuleStatus
from pb_studio.assistant_rules.schemas import AssistantRuleCreate
from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import set_chat_role
from pb_studio.core.config import Settings, get_settings
from pb_studio.knowledge import service as kb_service
from pb_studio.knowledge.constants import KnowledgeDocumentSourceType, KnowledgeDocumentStatus
from pb_studio.projects.constants import ProjectStatus
from pb_studio.projects.schemas import ProjectChatBindBody, ProjectChatUnbindBody, ProjectCreate
from pb_studio.projects.service import (
    archive_project,
    bind_chat_to_project,
    create_project,
    unbind_chat_from_project,
)
from pb_studio.sla.constants import SlaIncidentStatus, SlaSeverity
from pb_studio.sla.service import acknowledge_incident, resolve_incident
from pb_studio.summaries.constants import SummaryDeliveryStatus, SummaryStatus

templates = Jinja2Templates(
    directory=str(templates_dir()),
    context_processors=[
        lambda request: {
            "flash_success": request.query_params.get("fs"),
            "flash_error": request.query_params.get("fe"),
        }
    ],
)
templates.env.filters["admin_dt"] = format_admin_dt
templates.env.filters["admin_snip"] = snip_text

router = APIRouter(prefix="/admin", tags=["admin-ui"])

_admin_dep = [Depends(require_admin_ui)]


def _safe_token_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return False


def _validation_message(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"])
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)[:450]


def _bc(*segments: tuple[str, str | None]) -> list[dict[str, str | None]]:
    return [{"label": a, "href": b} for a, b in segments]


def _parse_uuid_optional(raw: str | None) -> UUID | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return UUID(str(raw).strip())
    except ValueError:
        return None


def _table(
    request: Request,
    *,
    nav: str,
    title: str,
    subtitle: str,
    columns: list[str],
    rows: list[list[str]],
    detail_prefix: str | None = None,
    detail_col: int = 0,
    breadcrumbs: list[dict[str, str | None]] | None = None,
    pagination: PaginationUrls | None = None,
    filter_action: str | None = None,
    filter_fields: list[dict[str, Any]] | None = None,
    filter_hidden: list[dict[str, str]] | None = None,
    badge_column_indices: list[int] | None = None,
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
            "detail_prefix": detail_prefix,
            "detail_col": detail_col,
            "breadcrumbs": breadcrumbs or [],
            "pagination": pagination,
            "filter_action": filter_action,
            "filter_fields": filter_fields or [],
            "filter_hidden": filter_hidden or [],
            "badge_column_indices": badge_column_indices or [],
        },
    )


def _not_found(
    request: Request,
    *,
    nav: str,
    title: str,
    message: str,
    back_href: str,
    breadcrumbs: list[dict[str, str | None]] | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "not_found.html",
        {
            "nav_active": nav,
            "title": title,
            "message": message,
            "back_href": back_href,
            "breadcrumbs": breadcrumbs or [],
        },
        status_code=status.HTTP_404_NOT_FOUND,
    )


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
        {"nav_active": "dashboard", "counts": counts, "breadcrumbs": _bc(("Обзор", None))},
    )


@router.get("/chats", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_chats(
    request: Request,
    session: DbSession,
    page: int | None = Query(None),
    limit: int | None = Query(None),
    role: str | None = Query(None),
    q: str | None = Query(None),
) -> HTMLResponse:
    lim = clamp_limit(limit)
    pg = clamp_page(page)
    total = await admin_data.count_chats_admin(session, role=role, q=q)
    page_eff = effective_page(pg, total, lim)
    off = offset_for(page_eff, lim)
    rows_db = await admin_data.list_chats_admin(session, role=role, q=q, limit=lim, offset=off)
    rows = [
        [
            str(c.id),
            str(c.telegram_chat_id),
            c.chat_type or "",
            snip_text(c.title, 72),
            c.chat_role,
            format_admin_dt(c.updated_at),
        ]
        for c in rows_db
    ]
    extra: dict[str, Any] = {}
    if role and role.strip():
        extra["role"] = role.strip()
    if q and q.strip():
        extra["q"] = q.strip()
    pag = build_pagination_urls(
        base_path="/admin/chats", page=page_eff, limit=lim, total=total, extra_query=extra
    )
    role_opts = [(m.value, m.value) for m in ChatRole]
    filter_fields: list[dict[str, Any]] = [
        {"name": "role", "label": "Роль", "type": "select", "value": (role or "").strip(), "options": role_opts},
        {
            "name": "q",
            "label": "Заголовок / telegram id",
            "type": "text",
            "value": (q or "").strip(),
            "placeholder": "подстрока title или числовой id",
        },
    ]
    return _table(
        request,
        nav="chats",
        title="Чаты",
        subtitle="studio_chats · фильтр и постраничный просмотр",
        columns=["id", "telegram_id", "type", "title", "chat_role", "updated"],
        rows=rows,
        detail_prefix="/admin/chats",
        badge_column_indices=[4],
        breadcrumbs=_bc(("Обзор", "/admin/"), ("Чаты", None)),
        pagination=pag,
        filter_action="/admin/chats",
        filter_fields=filter_fields,
        filter_hidden=[{"name": "limit", "value": str(lim)}],
    )


@router.get("/chats/{chat_id}", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_chat_detail(request: Request, session: DbSession, chat_id: UUID) -> HTMLResponse:
    chat = await admin_data.get_chat(session, chat_id)
    if chat is None:
        return _not_found(
            request,
            nav="chats",
            title="Чат не найден",
            message="Нет чата с таким id.",
            back_href="/admin/chats",
            breadcrumbs=_bc(("Обзор", "/admin/"), ("Чаты", "/admin/chats"), ("Не найден", None)),
        )
    links = await admin_data.list_project_links_for_chat(session, chat_id)
    role_choices = [m.value for m in ChatRole if m != ChatRole.CONTROL_GROUP]
    return templates.TemplateResponse(
        request,
        "chat_detail.html",
        {
            "nav_active": "chats",
            "chat": chat,
            "project_links": links,
            "role_choices": role_choices,
            "breadcrumbs": _bc(
                ("Обзор", "/admin/"),
                ("Чаты", "/admin/chats"),
                (snip_text(chat.title or str(chat.telegram_chat_id), 42), None),
            ),
        },
    )


@router.post("/chats/{chat_id}/role", dependencies=_admin_dep)
async def admin_chat_role_post(session: DbSession, chat_id: UUID, role: str = Form(...)) -> RedirectResponse:
    try:
        await set_chat_role(session, studio_chat_id=chat_id, role=role.strip())
    except ValueError as exc:
        return redirect_with_flash(f"/admin/chats/{chat_id}", error=str(exc))
    return redirect_with_flash(f"/admin/chats/{chat_id}", success="Роль обновлена.")


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
            breadcrumbs=_bc(("Обзор", "/admin/"), ("Control group", None)),
        )
    cg = view["control_group"]
    ch = view["chat"]
    rows = [
        [
            str(cg.id),
            str(ch.telegram_chat_id),
            ch.title or "",
            str(cg.is_active),
            format_admin_dt(cg.created_at),
        ]
    ]
    return _table(
        request,
        nav="cg",
        title="Control group",
        subtitle="Активная studio_control_groups + чат",
        columns=["cg_id", "telegram_chat_id", "title", "is_active", "created_at"],
        rows=rows,
        breadcrumbs=_bc(("Обзор", "/admin/"), ("Control group", None)),
        badge_column_indices=[3],
    )


@router.get("/summaries", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_summaries(
    request: Request,
    session: DbSession,
    page: int | None = Query(None),
    limit: int | None = Query(None),
    status: str | None = Query(None),
    delivery_status: str | None = Query(None),
) -> HTMLResponse:
    lim = clamp_limit(limit)
    pg = clamp_page(page)
    total = await admin_data.count_summaries_admin(session, status=status, delivery_status=delivery_status)
    page_eff = effective_page(pg, total, lim)
    off = offset_for(page_eff, lim)
    items = await admin_data.list_summaries_admin(
        session, status=status, delivery_status=delivery_status, limit=lim, offset=off
    )
    rows = [
        [
            str(s.id),
            str(s.chat_id),
            s.summary_type,
            s.status,
            s.delivery_status,
            format_admin_dt(s.period_start),
            format_admin_dt(s.period_end),
        ]
        for s in items
    ]
    extra: dict[str, Any] = {}
    if status and status.strip():
        extra["status"] = status.strip()
    if delivery_status and delivery_status.strip():
        extra["delivery_status"] = delivery_status.strip()
    pag = build_pagination_urls(
        base_path="/admin/summaries", page=page_eff, limit=lim, total=total, extra_query=extra
    )
    sum_status_opts = [
        (SummaryStatus.PENDING, SummaryStatus.PENDING),
        (SummaryStatus.GENERATED, SummaryStatus.GENERATED),
        (SummaryStatus.FAILED, SummaryStatus.FAILED),
    ]
    sum_del_opts = [
        (SummaryDeliveryStatus.NOT_REQUESTED, SummaryDeliveryStatus.NOT_REQUESTED),
        (
            SummaryDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY,
            SummaryDeliveryStatus.PENDING_CONTROL_GROUP_DELIVERY,
        ),
        (
            SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP,
            SummaryDeliveryStatus.DELIVERED_TO_CONTROL_GROUP,
        ),
        (SummaryDeliveryStatus.FAILED_RETRYABLE, SummaryDeliveryStatus.FAILED_RETRYABLE),
        (SummaryDeliveryStatus.FAILED_PERMANENT, SummaryDeliveryStatus.FAILED_PERMANENT),
    ]
    filter_fields: list[dict[str, Any]] = [
        {"name": "status", "label": "Статус", "type": "select", "value": (status or "").strip(), "options": sum_status_opts},
        {
            "name": "delivery_status",
            "label": "Доставка",
            "type": "select",
            "value": (delivery_status or "").strip(),
            "options": sum_del_opts,
        },
    ]
    return _table(
        request,
        nav="summaries",
        title="Сводки",
        subtitle="studio_chat_summaries",
        columns=["id", "chat_id", "type", "status", "delivery", "period_start", "period_end"],
        rows=rows,
        detail_prefix="/admin/chats",
        detail_col=1,
        badge_column_indices=[3, 4],
        breadcrumbs=_bc(("Обзор", "/admin/"), ("Сводки", None)),
        pagination=pag,
        filter_action="/admin/summaries",
        filter_fields=filter_fields,
        filter_hidden=[{"name": "limit", "value": str(lim)}],
    )


@router.post("/projects", dependencies=_admin_dep)
async def admin_projects_create_post(
    session: DbSession,
    slug: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
) -> RedirectResponse:
    try:
        body = ProjectCreate(slug=slug.strip(), name=name.strip(), description=description.strip() or None)
    except ValidationError as exc:
        return redirect_with_flash("/admin/projects", error=_validation_message(exc))
    try:
        row = await create_project(
            session,
            slug=body.slug,
            name=body.name,
            description=body.description,
            metadata_json=body.metadata_json,
        )
    except ValueError as exc:
        return redirect_with_flash("/admin/projects", error=str(exc))
    except IntegrityError:
        return redirect_with_flash("/admin/projects", error="slug уже занят")
    return redirect_with_flash(f"/admin/projects/{row.id}", success="Проект создан.")


@router.get("/projects", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_projects(
    request: Request,
    session: DbSession,
    page: int | None = Query(None),
    limit: int | None = Query(None),
    status: str | None = Query(None),
) -> HTMLResponse:
    lim = clamp_limit(limit)
    pg = clamp_page(page)
    total = await admin_data.count_projects_admin(session, status=status)
    page_eff = effective_page(pg, total, lim)
    off = offset_for(page_eff, lim)
    items = await admin_data.list_projects_admin(session, status=status, limit=lim, offset=off)
    rows = [[str(p.id), p.slug, p.name, p.status, format_admin_dt(p.updated_at)] for p in items]
    extra: dict[str, Any] = {}
    if status and status.strip():
        extra["status"] = status.strip()
    pag = build_pagination_urls(
        base_path="/admin/projects", page=page_eff, limit=lim, total=total, extra_query=extra
    )
    filter_fields: list[dict[str, Any]] = [
        {
            "name": "status",
            "label": "Статус",
            "type": "select",
            "value": (status or "").strip(),
            "options": [(ProjectStatus.ACTIVE, ProjectStatus.ACTIVE), (ProjectStatus.ARCHIVED, ProjectStatus.ARCHIVED)],
        },
    ]
    return templates.TemplateResponse(
        request,
        "projects_list.html",
        {
            "nav_active": "projects",
            "breadcrumbs": _bc(("Обзор", "/admin/"), ("Проекты", None)),
            "page_title": "Проекты",
            "page_subtitle": "studio_projects",
            "columns": ["id", "slug", "name", "status", "updated"],
            "rows": rows,
            "empty": len(rows) == 0,
            "detail_prefix": "/admin/projects",
            "detail_col": 0,
            "pagination": pag,
            "filter_action": "/admin/projects",
            "filter_fields": filter_fields,
            "filter_hidden": [{"name": "limit", "value": str(lim)}],
            "badge_column_indices": [3],
        },
    )


@router.get("/projects/{project_id}", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_project_detail(request: Request, session: DbSession, project_id: UUID) -> HTMLResponse:
    project = await admin_data.get_project_row(session, project_id)
    if project is None:
        return _not_found(
            request,
            nav="projects",
            title="Проект не найден",
            message="Нет проекта с таким id.",
            back_href="/admin/projects",
            breadcrumbs=_bc(("Обзор", "/admin/"), ("Проекты", "/admin/projects"), ("Не найден", None)),
        )
    chat_links = await admin_data.list_project_chat_links(session, project_id, active_only=False)
    chats_select = await admin_data.list_chats_for_select(session)
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {
            "nav_active": "projects",
            "project": project,
            "chat_links": chat_links,
            "chats_select": chats_select,
            "breadcrumbs": _bc(("Обзор", "/admin/"), ("Проекты", "/admin/projects"), (project.slug, None)),
        },
    )


@router.post("/projects/{project_id}/archive", dependencies=_admin_dep)
async def admin_project_archive_post(session: DbSession, project_id: UUID) -> RedirectResponse:
    row = await archive_project(session, project_id)
    if row is None:
        return redirect_with_flash("/admin/projects", error="Проект не найден")
    return redirect_with_flash(f"/admin/projects/{project_id}", success="Проект заархивирован.")


@router.post("/projects/{project_id}/bind-chat", dependencies=_admin_dep)
async def admin_project_bind_post(
    session: DbSession,
    project_id: UUID,
    chat_id: UUID = Form(...),
    role_in_project: str = Form("secondary"),
) -> RedirectResponse:
    try:
        body = ProjectChatBindBody(chat_id=chat_id, role_in_project=role_in_project.strip())
    except ValidationError as exc:
        return redirect_with_flash(f"/admin/projects/{project_id}", error=_validation_message(exc))
    try:
        await bind_chat_to_project(
            session,
            project_id=project_id,
            chat_id=body.chat_id,
            role_in_project=body.role_in_project,
        )
    except ValueError as exc:
        return redirect_with_flash(f"/admin/projects/{project_id}", error=str(exc))
    return redirect_with_flash(f"/admin/projects/{project_id}", success="Чат привязан.")


@router.post("/projects/{project_id}/unbind-chat", dependencies=_admin_dep)
async def admin_project_unbind_post(session: DbSession, project_id: UUID, chat_id: UUID = Form(...)) -> RedirectResponse:
    body = ProjectChatUnbindBody(chat_id=chat_id)
    row = await unbind_chat_from_project(session, project_id=project_id, chat_id=body.chat_id)
    if row is None:
        return redirect_with_flash(f"/admin/projects/{project_id}", error="Связь не найдена")
    return redirect_with_flash(f"/admin/projects/{project_id}", success="Чат отвязан.")


@router.get("/sla/incidents", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_sla_incidents(
    request: Request,
    session: DbSession,
    page: int | None = Query(None),
    limit: int | None = Query(None),
    status: str | None = Query(None),
    severity: str | None = Query(None),
) -> HTMLResponse:
    lim = clamp_limit(limit)
    pg = clamp_page(page)
    total = await admin_data.count_sla_incidents_admin(session, status=status, severity=severity)
    page_eff = effective_page(pg, total, lim)
    off = offset_for(page_eff, lim)
    items = await admin_data.list_sla_incidents_admin(
        session, status=status, severity=severity, limit=lim, offset=off
    )
    rows = [
        [
            str(i.id),
            str(i.chat_id),
            i.status,
            i.severity,
            format_admin_dt(i.due_at),
            format_admin_dt(i.created_at),
        ]
        for i in items
    ]
    extra: dict[str, Any] = {}
    if status and status.strip():
        extra["status"] = status.strip()
    if severity and severity.strip():
        extra["severity"] = severity.strip()
    pag = build_pagination_urls(
        base_path="/admin/sla/incidents", page=page_eff, limit=lim, total=total, extra_query=extra
    )
    st_opts = [(m.value, m.value) for m in SlaIncidentStatus]
    sev_opts = [(m.value, m.value) for m in SlaSeverity]
    filter_fields: list[dict[str, Any]] = [
        {"name": "status", "label": "Статус", "type": "select", "value": (status or "").strip(), "options": st_opts},
        {"name": "severity", "label": "Важность", "type": "select", "value": (severity or "").strip(), "options": sev_opts},
    ]
    return _table(
        request,
        nav="sla",
        title="SLA инциденты",
        subtitle="studio_sla_incidents",
        columns=["id", "chat_id", "status", "severity", "due_at", "created"],
        rows=rows,
        detail_prefix="/admin/sla/incidents",
        badge_column_indices=[2, 3],
        breadcrumbs=_bc(("Обзор", "/admin/"), ("SLA инциденты", None)),
        pagination=pag,
        filter_action="/admin/sla/incidents",
        filter_fields=filter_fields,
        filter_hidden=[{"name": "limit", "value": str(lim)}],
    )


@router.get("/sla/incidents/{incident_id}", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_sla_incident_detail(request: Request, session: DbSession, incident_id: UUID) -> HTMLResponse:
    inc = await admin_data.get_sla_incident(session, incident_id)
    if inc is None:
        return _not_found(
            request,
            nav="sla",
            title="Инцидент не найден",
            message="Нет инцидента с таким id.",
            back_href="/admin/sla/incidents",
            breadcrumbs=_bc(("Обзор", "/admin/"), ("SLA инциденты", "/admin/sla/incidents"), ("Не найден", None)),
        )
    return templates.TemplateResponse(
        request,
        "sla_incident_detail.html",
        {
            "nav_active": "sla",
            "inc": inc,
            "breadcrumbs": _bc(
                ("Обзор", "/admin/"),
                ("SLA инциденты", "/admin/sla/incidents"),
                (str(inc.id)[:13] + "…", None),
            ),
        },
    )


@router.post("/sla/incidents/{incident_id}/ack", dependencies=_admin_dep)
async def admin_sla_ack_post(session: DbSession, incident_id: UUID) -> RedirectResponse:
    row = await acknowledge_incident(session, incident_id)
    if row is None:
        return redirect_with_flash("/admin/sla/incidents", error="Инцидент не найден")
    return redirect_with_flash(f"/admin/sla/incidents/{incident_id}", success="Статус обновлён (ack).")


@router.post("/sla/incidents/{incident_id}/resolve", dependencies=_admin_dep)
async def admin_sla_resolve_post(session: DbSession, incident_id: UUID) -> RedirectResponse:
    row = await resolve_incident(session, incident_id)
    if row is None:
        return redirect_with_flash("/admin/sla/incidents", error="Инцидент не найден")
    return redirect_with_flash(f"/admin/sla/incidents/{incident_id}", success="Инцидент помечен resolved.")


@router.post("/knowledge/documents/upload", dependencies=_admin_dep)
async def admin_kb_upload_post(
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
    title: str = Form(""),
    project_id: str = Form(""),
) -> RedirectResponse:
    if not settings.studio_kb_enabled:
        return redirect_with_flash("/admin/knowledge/documents", error="KB выключен (STUDIO_KB_ENABLED=false).")
    raw_name = file.filename or "upload"
    data = await file.read()
    if len(data) > settings.studio_kb_upload_max_bytes:
        return redirect_with_flash("/admin/knowledge/documents", error="Файл слишком большой.")
    pid: UUID | None = None
    if project_id.strip():
        try:
            pid = UUID(project_id.strip())
        except ValueError:
            return redirect_with_flash("/admin/knowledge/documents", error="Некорректный project_id.")
    try:
        doc, _ver, _created = await kb_service.ingest_new_document_from_upload(
            session,
            title=(title or "").strip(),
            project_id=pid,
            filename=raw_name,
            data=data,
            settings=settings,
        )
    except ValueError as exc:
        return redirect_with_flash("/admin/knowledge/documents", error=str(exc))
    return redirect_with_flash(f"/admin/knowledge/documents/{doc.id}", success="Документ загружен.")


@router.post("/knowledge/documents/{document_id}/upload-version", dependencies=_admin_dep)
async def admin_kb_version_upload_post(
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    document_id: UUID,
    file: UploadFile = File(...),
) -> RedirectResponse:
    if not settings.studio_kb_enabled:
        return redirect_with_flash(f"/admin/knowledge/documents/{document_id}", error="KB выключен.")
    raw_name = file.filename or "upload"
    data = await file.read()
    if len(data) > settings.studio_kb_upload_max_bytes:
        return redirect_with_flash(f"/admin/knowledge/documents/{document_id}", error="Файл слишком большой.")
    try:
        await kb_service.ingest_file_upload_to_document(
            session,
            document_id,
            filename=raw_name,
            data=data,
            settings=settings,
        )
    except ValueError as exc:
        return redirect_with_flash(f"/admin/knowledge/documents/{document_id}", error=str(exc))
    return redirect_with_flash(f"/admin/knowledge/documents/{document_id}", success="Версия добавлена.")


@router.get("/knowledge/documents", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_kb_documents(
    request: Request,
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    page: int | None = Query(None),
    limit: int | None = Query(None),
    status: str | None = Query(None),
    source_type: str | None = Query(None),
    project_id: str | None = Query(None),
) -> HTMLResponse:
    lim = clamp_limit(limit)
    pg = clamp_page(page)
    pid = _parse_uuid_optional(project_id)
    total = await admin_data.count_knowledge_documents_admin(
        session, status=status, source_type=source_type, project_id=pid
    )
    page_eff = effective_page(pg, total, lim)
    off = offset_for(page_eff, lim)
    items = await admin_data.list_knowledge_documents_admin(
        session,
        status=status,
        source_type=source_type,
        project_id=pid,
        limit=lim,
        offset=off,
    )
    rows = [
        [
            str(d.id),
            snip_text(d.title, 64),
            d.status,
            d.source_type,
            str(d.project_id or ""),
            format_admin_dt(d.updated_at),
        ]
        for d in items
    ]
    extra: dict[str, Any] = {}
    if status and status.strip():
        extra["status"] = status.strip()
    if source_type and source_type.strip():
        extra["source_type"] = source_type.strip()
    if pid:
        extra["project_id"] = str(pid)
    pag = build_pagination_urls(
        base_path="/admin/knowledge/documents", page=page_eff, limit=lim, total=total, extra_query=extra
    )
    kb_status_opts = [
        (KnowledgeDocumentStatus.DRAFT, KnowledgeDocumentStatus.DRAFT),
        (KnowledgeDocumentStatus.ACTIVE, KnowledgeDocumentStatus.ACTIVE),
        (KnowledgeDocumentStatus.ARCHIVED, KnowledgeDocumentStatus.ARCHIVED),
        (KnowledgeDocumentStatus.FAILED, KnowledgeDocumentStatus.FAILED),
    ]
    src_opts = [
        (KnowledgeDocumentSourceType.MANUAL, KnowledgeDocumentSourceType.MANUAL),
        (KnowledgeDocumentSourceType.FILE, KnowledgeDocumentSourceType.FILE),
        (KnowledgeDocumentSourceType.URL, KnowledgeDocumentSourceType.URL),
        (KnowledgeDocumentSourceType.TELEGRAM, KnowledgeDocumentSourceType.TELEGRAM),
        (KnowledgeDocumentSourceType.GOOGLE_DRIVE, KnowledgeDocumentSourceType.GOOGLE_DRIVE),
    ]
    projects_for_filter = await admin_data.list_projects_all_for_filter(session)
    project_opts = [(str(p.id), f"{p.slug} · {snip_text(p.name, 48)}") for p in projects_for_filter]
    filter_fields: list[dict[str, Any]] = [
        {"name": "status", "label": "Статус", "type": "select", "value": (status or "").strip(), "options": kb_status_opts},
        {
            "name": "source_type",
            "label": "Источник",
            "type": "select",
            "value": (source_type or "").strip(),
            "options": src_opts,
        },
        {
            "name": "project_id",
            "label": "Проект",
            "type": "select",
            "value": str(pid) if pid else "",
            "options": project_opts,
        },
    ]
    return templates.TemplateResponse(
        request,
        "kb_documents_list.html",
        {
            "nav_active": "kb",
            "breadcrumbs": _bc(("Обзор", "/admin/"), ("KB документы", None)),
            "page_title": "KB документы",
            "page_subtitle": "studio_knowledge_documents",
            "columns": ["id", "title", "status", "source", "project_id", "updated"],
            "rows": rows,
            "empty": len(rows) == 0,
            "detail_prefix": "/admin/knowledge/documents",
            "detail_col": 0,
            "kb_upload_enabled": settings.studio_kb_enabled,
            "pagination": pag,
            "filter_action": "/admin/knowledge/documents",
            "filter_fields": filter_fields,
            "filter_hidden": [{"name": "limit", "value": str(lim)}],
            "badge_column_indices": [2, 3],
            "row_link_bases": {4: "/admin/projects"},
        },
    )


@router.get("/knowledge/documents/{document_id}", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_kb_document_detail(
    request: Request,
    session: DbSession,
    document_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    doc, versions = await admin_data.get_kb_document_bundle(session, document_id)
    if doc is None:
        return _not_found(
            request,
            nav="kb",
            title="Документ не найден",
            message="Нет документа с таким id.",
            back_href="/admin/knowledge/documents",
            breadcrumbs=_bc(("Обзор", "/admin/"), ("KB документы", "/admin/knowledge/documents"), ("Не найден", None)),
        )
    return templates.TemplateResponse(
        request,
        "kb_document_detail.html",
        {
            "nav_active": "kb",
            "doc": doc,
            "versions": versions,
            "kb_upload_enabled": settings.studio_kb_enabled,
            "breadcrumbs": _bc(
                ("Обзор", "/admin/"),
                ("KB документы", "/admin/knowledge/documents"),
                (snip_text(doc.title, 44), None),
            ),
        },
    )


@router.post("/assistant-rules", dependencies=_admin_dep)
async def admin_assistant_rule_create_post(
    session: DbSession,
    scope: str = Form(...),
    rule_text: str = Form(...),
    project_id: str = Form(""),
    chat_id: str = Form(""),
) -> RedirectResponse:
    pid: UUID | None = None
    cid: UUID | None = None
    if project_id.strip():
        try:
            pid = UUID(project_id.strip())
        except ValueError:
            return redirect_with_flash("/admin/assistant-rules", error="Некорректный project_id (UUID).")
    if chat_id.strip():
        try:
            cid = UUID(chat_id.strip())
        except ValueError:
            return redirect_with_flash("/admin/assistant-rules", error="Некорректный chat_id (UUID).")
    try:
        body = AssistantRuleCreate(
            scope=scope.strip().lower(),
            rule_text=rule_text,
            project_id=pid,
            chat_id=cid,
        )
    except ValidationError as exc:
        return redirect_with_flash("/admin/assistant-rules", error=_validation_message(exc))
    try:
        row = await rules_service.create_rule(
            session,
            scope=body.scope,
            rule_text=body.rule_text,
            project_id=body.project_id,
            chat_id=body.chat_id,
            source=body.source,
            metadata_json=body.metadata_json,
        )
    except ValueError as exc:
        return redirect_with_flash("/admin/assistant-rules", error=str(exc))
    return redirect_with_flash(f"/admin/assistant-rules/{row.id}", success="Правило создано.")


@router.get("/assistant-rules", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_assistant_rules(
    request: Request,
    session: DbSession,
    page: int | None = Query(None),
    limit: int | None = Query(None),
    status: str | None = Query(None),
    scope: str | None = Query(None),
) -> HTMLResponse:
    lim = clamp_limit(limit)
    pg = clamp_page(page)
    total = await admin_data.count_assistant_rules_admin(session, status=status, scope=scope)
    page_eff = effective_page(pg, total, lim)
    off = offset_for(page_eff, lim)
    items = await admin_data.list_assistant_rules_admin(
        session, status=status, scope=scope, limit=lim, offset=off
    )
    rows = [
        [
            str(r.id),
            r.scope,
            r.status,
            snip_text(r.rule_text, 96),
            str(r.project_id or ""),
            str(r.chat_id or ""),
            format_admin_dt(r.updated_at),
        ]
        for r in items
    ]
    extra: dict[str, Any] = {}
    if status and status.strip():
        extra["status"] = status.strip()
    if scope and scope.strip():
        extra["scope"] = scope.strip().lower()
    pag = build_pagination_urls(
        base_path="/admin/assistant-rules", page=page_eff, limit=lim, total=total, extra_query=extra
    )
    projects_sel = await admin_data.list_projects_active_for_select(session)
    chats_sel = await admin_data.list_chats_for_select(session)
    scopes = [AssistantRuleScope.GLOBAL, AssistantRuleScope.PROJECT, AssistantRuleScope.CHAT]
    scope_opts = [(s, s) for s in scopes]
    status_opts = [
        (AssistantRuleStatus.ACTIVE, AssistantRuleStatus.ACTIVE),
        (AssistantRuleStatus.DISABLED, AssistantRuleStatus.DISABLED),
    ]
    filter_fields: list[dict[str, Any]] = [
        {"name": "scope", "label": "Scope", "type": "select", "value": (scope or "").strip().lower(), "options": scope_opts},
        {"name": "status", "label": "Статус", "type": "select", "value": (status or "").strip(), "options": status_opts},
    ]
    return templates.TemplateResponse(
        request,
        "assistant_rules_list.html",
        {
            "nav_active": "rules",
            "breadcrumbs": _bc(("Обзор", "/admin/"), ("Правила", None)),
            "page_title": "Правила ассистента",
            "page_subtitle": "studio_assistant_rules",
            "columns": ["id", "scope", "status", "rule_text", "project_id", "chat_id", "updated"],
            "rows": rows,
            "empty": len(rows) == 0,
            "detail_prefix": "/admin/assistant-rules",
            "detail_col": 0,
            "projects_select": projects_sel,
            "chats_select": chats_sel,
            "scopes": scopes,
            "pagination": pag,
            "filter_action": "/admin/assistant-rules",
            "filter_fields": filter_fields,
            "filter_hidden": [{"name": "limit", "value": str(lim)}],
            "badge_column_indices": [1, 2],
            "row_link_bases": {4: "/admin/projects", 5: "/admin/chats"},
        },
    )


@router.get("/assistant-rules/{rule_id}", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_assistant_rule_detail(request: Request, session: DbSession, rule_id: UUID) -> HTMLResponse:
    rule = await admin_data.get_assistant_rule(session, rule_id)
    if rule is None:
        return _not_found(
            request,
            nav="rules",
            title="Правило не найдено",
            message="Нет правила с таким id.",
            back_href="/admin/assistant-rules",
            breadcrumbs=_bc(("Обзор", "/admin/"), ("Правила", "/admin/assistant-rules"), ("Не найден", None)),
        )
    return templates.TemplateResponse(
        request,
        "assistant_rule_detail.html",
        {
            "nav_active": "rules",
            "rule": rule,
            "breadcrumbs": _bc(
                ("Обзор", "/admin/"),
                ("Правила", "/admin/assistant-rules"),
                (str(rule.id)[:13] + "…", None),
            ),
        },
    )


@router.post("/assistant-rules/{rule_id}/disable", dependencies=_admin_dep)
async def admin_assistant_rule_disable_post(
    session: DbSession, rule_id: UUID, reason: str = Form("")
) -> RedirectResponse:
    row = await rules_service.disable_rule(session, rule_id, reason=reason.strip() or None, actor_telegram_user_id=None)
    if row is None:
        return redirect_with_flash("/admin/assistant-rules", error="Правило не найдено")
    return redirect_with_flash(f"/admin/assistant-rules/{rule_id}", success="Правило отключено.")


@router.get("/history-import/jobs", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_history_jobs(
    request: Request,
    session: DbSession,
    page: int | None = Query(None),
    limit: int | None = Query(None),
) -> HTMLResponse:
    lim = clamp_limit(limit)
    pg = clamp_page(page)
    total = await admin_data.count_history_import_jobs(session)
    page_eff = effective_page(pg, total, lim)
    off = offset_for(page_eff, lim)
    items = await admin_data.list_history_import_jobs_page(session, limit=lim, offset=off)
    rows = [
        [
            str(j.id),
            j.source_type,
            j.status,
            str(j.imported_chat_count),
            str(j.imported_message_count),
            str(j.skipped_count),
            snip_text(j.file_name or "", 48),
            format_admin_dt(j.created_at),
        ]
        for j in items
    ]
    pag = build_pagination_urls(
        base_path="/admin/history-import/jobs", page=page_eff, limit=lim, total=total, extra_query={}
    )
    return _table(
        request,
        nav="hist",
        title="Импорт истории",
        subtitle="studio_history_import_jobs",
        columns=["id", "source", "status", "chats", "msgs", "skipped", "file", "created"],
        rows=rows,
        breadcrumbs=_bc(("Обзор", "/admin/"), ("Импорт истории", None)),
        badge_column_indices=[2],
        pagination=pag,
        filter_hidden=[{"name": "limit", "value": str(lim)}],
    )
