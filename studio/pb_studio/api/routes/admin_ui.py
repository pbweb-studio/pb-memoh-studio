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
from pb_studio.admin_ui.auth import (
    COOKIE_NAME,
    issue_session_cookie,
    redirect_if_logged_in,
    require_admin_ui,
)
from pb_studio.admin_ui.flash import redirect_with_flash
from pb_studio.api.deps import DbSession
from pb_studio.assistant_rules import service as rules_service
from pb_studio.assistant_rules.constants import AssistantRuleScope
from pb_studio.assistant_rules.schemas import AssistantRuleCreate
from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import set_chat_role
from pb_studio.core.config import Settings, get_settings
from pb_studio.knowledge import service as kb_service
from pb_studio.projects.schemas import ProjectChatBindBody, ProjectChatUnbindBody, ProjectCreate
from pb_studio.projects.service import (
    archive_project,
    bind_chat_to_project,
    create_project,
    unbind_chat_from_project,
)
from pb_studio.sla.service import acknowledge_incident, resolve_incident

templates = Jinja2Templates(
    directory=str(templates_dir()),
    context_processors=[
        lambda request: {
            "flash_success": request.query_params.get("fs"),
            "flash_error": request.query_params.get("fe"),
        }
    ],
)

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
        },
    )


def _not_found(request: Request, *, nav: str, title: str, message: str, back_href: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "not_found.html",
        {"nav_active": nav, "title": title, "message": message, "back_href": back_href},
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
        {"nav_active": "dashboard", "counts": counts},
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
        detail_prefix="/admin/chats",
    )


@router.get("/chats/{chat_id}", response_class=HTMLResponse, dependencies=_admin_dep)
async def admin_chat_detail(request: Request, session: DbSession, chat_id: UUID) -> HTMLResponse:
    chat = await admin_data.get_chat(session, chat_id)
    if chat is None:
        return _not_found(request, nav="chats", title="Чат не найден", message="Нет чата с таким id.", back_href="/admin/chats")
    links = await admin_data.list_project_links_for_chat(session, chat_id)
    role_choices = [m.value for m in ChatRole if m != ChatRole.CONTROL_GROUP]
    return templates.TemplateResponse(
        request,
        "chat_detail.html",
        {"nav_active": "chats", "chat": chat, "project_links": links, "role_choices": role_choices},
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
        detail_prefix="/admin/chats",
        detail_col=1,
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
async def admin_projects(request: Request, session: DbSession) -> HTMLResponse:
    items = await admin_data.list_projects(session)
    rows = [[str(p.id), p.slug, p.name, str(p.created_at)] for p in items]
    return templates.TemplateResponse(
        request,
        "projects_list.html",
        {
            "nav_active": "projects",
            "page_title": "Проекты",
            "page_subtitle": "studio_projects",
            "columns": ["id", "slug", "name", "created_at"],
            "rows": rows,
            "empty": len(rows) == 0,
            "detail_prefix": "/admin/projects",
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
        )
    chat_links = await admin_data.list_project_chat_links(session, project_id, active_only=False)
    chats_select = await admin_data.list_chats_for_select(session)
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {"nav_active": "projects", "project": project, "chat_links": chat_links, "chats_select": chats_select},
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
        detail_prefix="/admin/sla/incidents",
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
        )
    return templates.TemplateResponse(request, "sla_incident_detail.html", {"nav_active": "sla", "inc": inc})


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
    request: Request, session: DbSession, settings: Annotated[Settings, Depends(get_settings)]
) -> HTMLResponse:
    items = await admin_data.list_knowledge_documents(session)
    rows = [[str(d.id), d.title, d.status, str(d.project_id or ""), str(d.created_at)] for d in items]
    return templates.TemplateResponse(
        request,
        "kb_documents_list.html",
        {
            "nav_active": "kb",
            "page_title": "KB документы",
            "page_subtitle": "studio_knowledge_documents",
            "columns": ["id", "title", "status", "project_id", "created_at"],
            "rows": rows,
            "empty": len(rows) == 0,
            "detail_prefix": "/admin/knowledge/documents",
            "kb_upload_enabled": settings.studio_kb_enabled,
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
        )
    return templates.TemplateResponse(
        request,
        "kb_document_detail.html",
        {
            "nav_active": "kb",
            "doc": doc,
            "versions": versions,
            "kb_upload_enabled": settings.studio_kb_enabled,
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
async def admin_assistant_rules(request: Request, session: DbSession) -> HTMLResponse:
    items = await admin_data.list_assistant_rules(session)
    rows = [
        [str(r.id), r.scope, r.status, (r.rule_text or "")[:120], str(r.project_id or ""), str(r.chat_id or "")]
        for r in items
    ]
    projects_sel = await admin_data.list_projects_active_for_select(session)
    chats_sel = await admin_data.list_chats_for_select(session)
    scopes = [AssistantRuleScope.GLOBAL, AssistantRuleScope.PROJECT, AssistantRuleScope.CHAT]
    return templates.TemplateResponse(
        request,
        "assistant_rules_list.html",
        {
            "nav_active": "rules",
            "page_title": "Правила ассистента",
            "page_subtitle": "studio_assistant_rules",
            "columns": ["id", "scope", "status", "rule_text", "project_id", "chat_id"],
            "rows": rows,
            "empty": len(rows) == 0,
            "detail_prefix": "/admin/assistant-rules",
            "projects_select": projects_sel,
            "chats_select": chats_sel,
            "scopes": scopes,
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
        )
    return templates.TemplateResponse(request, "assistant_rule_detail.html", {"nav_active": "rules", "rule": rule})


@router.post("/assistant-rules/{rule_id}/disable", dependencies=_admin_dep)
async def admin_assistant_rule_disable_post(
    session: DbSession, rule_id: UUID, reason: str = Form("")
) -> RedirectResponse:
    row = await rules_service.disable_rule(session, rule_id, reason=reason.strip() or None, actor_telegram_user_id=None)
    if row is None:
        return redirect_with_flash("/admin/assistant-rules", error="Правило не найдено")
    return redirect_with_flash(f"/admin/assistant-rules/{rule_id}", success="Правило отключено.")


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
