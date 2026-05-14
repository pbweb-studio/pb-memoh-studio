from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from pb_studio.api.deps import DbSession, verify_admin_optional
from pb_studio.control_commands.parser import period_bounds_utc
from pb_studio.core.config import get_settings
from pb_studio.project_digests.constants import ProjectDigestType
from pb_studio.project_digests.schemas import ProjectDigestOut, ProjectDigestPeriodBody
from pb_studio.project_digests.service import (
    generate_or_get_project_digest_for_period,
    generate_or_get_project_digest_latest,
    list_project_digests,
)
from pb_studio.projects.schemas import (
    ProjectChatBindBody,
    ProjectChatOut,
    ProjectChatUnbindBody,
    ProjectCreate,
    ProjectOut,
    ProjectPatch,
)
from pb_studio.summaries.constants import SummaryType
from pb_studio.summaries.product import utc_today_period, utc_yesterday_period
from pb_studio.projects.service import (
    archive_project,
    bind_chat_to_project,
    create_project,
    get_project,
    list_project_chats,
    list_projects,
    patch_project,
    unbind_chat_from_project,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut], dependencies=[Depends(verify_admin_optional)])
async def get_projects(
    session: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ProjectOut]:
    rows = await list_projects(session, status=status_filter, limit=limit)
    return [ProjectOut.model_validate(r) for r in rows]


@router.post("", response_model=ProjectOut, dependencies=[Depends(verify_admin_optional)])
async def post_project(session: DbSession, body: ProjectCreate) -> ProjectOut:
    try:
        row = await create_project(
            session,
            slug=body.slug,
            name=body.name,
            description=body.description,
            metadata_json=body.metadata_json,
        )
        return ProjectOut.model_validate(row)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="slug already exists") from exc


@router.get("/{project_id}", response_model=ProjectOut, dependencies=[Depends(verify_admin_optional)])
async def get_project_by_id(session: DbSession, project_id: UUID) -> ProjectOut:
    row = await get_project(session, project_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return ProjectOut.model_validate(row)


@router.patch("/{project_id}", response_model=ProjectOut, dependencies=[Depends(verify_admin_optional)])
async def patch_project_by_id(session: DbSession, project_id: UUID, body: ProjectPatch) -> ProjectOut:
    updates = body.model_dump(exclude_unset=True)
    row = await patch_project(session, project_id, **updates)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return ProjectOut.model_validate(row)


@router.post("/{project_id}/archive", response_model=ProjectOut, dependencies=[Depends(verify_admin_optional)])
async def post_project_archive(session: DbSession, project_id: UUID) -> ProjectOut:
    row = await archive_project(session, project_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return ProjectOut.model_validate(row)


@router.post(
    "/{project_id}/bind-chat",
    response_model=ProjectChatOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_bind_chat(session: DbSession, project_id: UUID, body: ProjectChatBindBody) -> ProjectChatOut:
    try:
        link, _out = await bind_chat_to_project(
            session,
            project_id=project_id,
            chat_id=body.chat_id,
            role_in_project=body.role_in_project,
        )
        return ProjectChatOut.model_validate(link)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{project_id}/unbind-chat",
    response_model=ProjectChatOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_unbind_chat(
    session: DbSession, project_id: UUID, body: ProjectChatUnbindBody
) -> ProjectChatOut:
    row = await unbind_chat_from_project(session, project_id=project_id, chat_id=body.chat_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="link not found")
    return ProjectChatOut.model_validate(row)


@router.get(
    "/{project_id}/chats",
    response_model=list[ProjectChatOut],
    dependencies=[Depends(verify_admin_optional)],
)
async def get_project_chats(
    session: DbSession,
    project_id: UUID,
    include_inactive: bool = Query(default=False),
) -> list[ProjectChatOut]:
    if await get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    rows = await list_project_chats(session, project_id, active_only=not include_inactive)
    return [ProjectChatOut.model_validate(r) for r in rows]


@router.get(
    "/{project_id}/digests",
    response_model=list[ProjectDigestOut],
    dependencies=[Depends(verify_admin_optional)],
)
async def get_project_digests(
    session: DbSession,
    project_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ProjectDigestOut]:
    if await get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    rows = await list_project_digests(session, project_id, limit=limit)
    return [ProjectDigestOut.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/digests/today",
    response_model=ProjectDigestOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_project_digest_today(session: DbSession, project_id: UUID) -> ProjectDigestOut:
    if await get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    settings = get_settings()
    p0, p1 = utc_today_period()
    try:
        row, _created = await generate_or_get_project_digest_for_period(
            session,
            project_id=project_id,
            digest_type=ProjectDigestType.DAILY.value,
            period_start=p0,
            period_end=p1,
            settings=settings,
            summary_type_for_chats=SummaryType.DAILY,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProjectDigestOut.model_validate(row)


@router.post(
    "/{project_id}/digests/yesterday",
    response_model=ProjectDigestOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_project_digest_yesterday(session: DbSession, project_id: UUID) -> ProjectDigestOut:
    if await get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    settings = get_settings()
    p0, p1 = utc_yesterday_period()
    try:
        row, _created = await generate_or_get_project_digest_for_period(
            session,
            project_id=project_id,
            digest_type=ProjectDigestType.DAILY.value,
            period_start=p0,
            period_end=p1,
            settings=settings,
            summary_type_for_chats=SummaryType.DAILY,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProjectDigestOut.model_validate(row)


@router.post(
    "/{project_id}/digests/period",
    response_model=ProjectDigestOut,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_project_digest_period(
    session: DbSession, project_id: UUID, body: ProjectDigestPeriodBody
) -> ProjectDigestOut:
    if await get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    settings = get_settings()
    try:
        p0, p1 = period_bounds_utc(body.date_a, body.date_b)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        row, _created = await generate_or_get_project_digest_for_period(
            session,
            project_id=project_id,
            digest_type=ProjectDigestType.MANUAL.value,
            period_start=p0,
            period_end=p1,
            settings=settings,
            summary_type_for_chats=SummaryType.MANUAL,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProjectDigestOut.model_validate(row)
