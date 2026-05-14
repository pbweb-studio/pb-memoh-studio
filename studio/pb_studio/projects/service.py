from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.control_group.constants import ChatRole
from pb_studio.control_group.service import get_control_group_chat
from pb_studio.event_mirror.models import StudioChat
from pb_studio.projects.constants import ProjectStatus, RoleInProject
from pb_studio.projects.models import StudioProject, StudioProjectChat

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_slug(slug: str) -> str:
    s = slug.strip().lower()
    if not _SLUG_RE.match(s):
        raise ValueError("invalid slug: use lowercase letters, digits, hyphen, underscore; must start with letter or digit")
    return s


def _valid_role_in_project(role: str) -> str:
    allowed = {m.value for m in RoleInProject}
    if role not in allowed:
        raise ValueError(f"invalid role_in_project: {role!r}")
    return role


async def create_project(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> StudioProject:
    s = validate_slug(slug)
    row = StudioProject(
        slug=s,
        name=name.strip(),
        description=description,
        status=ProjectStatus.ACTIVE.value,
        metadata_json=metadata_json,
    )
    session.add(row)
    await session.flush()
    return row


async def list_projects(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[StudioProject]:
    lim = min(max(limit, 1), 500)
    stmt = select(StudioProject).order_by(StudioProject.created_at.desc()).limit(lim)
    if status:
        stmt = stmt.where(StudioProject.status == status)
    return list((await session.scalars(stmt)).all())


async def get_project(session: AsyncSession, project_id: UUID) -> StudioProject | None:
    return await session.get(StudioProject, project_id)


async def get_project_by_slug(session: AsyncSession, slug: str) -> StudioProject | None:
    try:
        s = validate_slug(slug)
    except ValueError:
        return None
    return await session.scalar(select(StudioProject).where(StudioProject.slug == s))


async def patch_project(
    session: AsyncSession,
    project_id: UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> StudioProject | None:
    row = await session.get(StudioProject, project_id)
    if row is None:
        return None
    if row.status == ProjectStatus.ARCHIVED.value:
        return row
    if name is not None:
        row.name = name.strip()
    if description is not None:
        row.description = description
    if metadata_json is not None:
        row.metadata_json = metadata_json
    row.updated_at = utcnow()
    return row


async def archive_project(session: AsyncSession, project_id: UUID) -> StudioProject | None:
    row = await session.get(StudioProject, project_id)
    if row is None:
        return None
    now = utcnow()
    row.status = ProjectStatus.ARCHIVED.value
    row.archived_at = now
    row.updated_at = now
    return row


async def bind_chat_to_project(
    session: AsyncSession,
    *,
    project_id: UUID,
    chat_id: UUID,
    role_in_project: str,
) -> tuple[StudioProjectChat, str]:
    """Returns (link, outcome) where outcome is 'created' | 'reactivated' | 'noop_active'."""
    proj = await session.get(StudioProject, project_id)
    if proj is None:
        raise ValueError("project not found")
    if proj.status != ProjectStatus.ACTIVE.value:
        raise ValueError("project is archived")
    chat = await session.get(StudioChat, chat_id)
    if chat is None:
        raise ValueError("chat not found")

    cg = await get_control_group_chat(session)
    if cg is not None and chat.id == cg.id:
        raise ValueError("cannot bind active control group chat")

    if chat.chat_role == ChatRole.CONTROL_GROUP.value:
        raise ValueError("cannot bind control_group role chat")

    role_ip = _valid_role_in_project(role_in_project)

    if chat.chat_role in (ChatRole.INTERNAL_CHAT.value, ChatRole.SERVICE_CHAT.value):
        raise ValueError("cannot bind internal_chat or service_chat")

    if chat.chat_role in (ChatRole.UNKNOWN.value, ChatRole.CLIENT_CHAT.value):
        chat.chat_role = ChatRole.PROJECT_CHAT.value
        chat.updated_at = utcnow()

    existing = await session.scalar(
        select(StudioProjectChat).where(
            StudioProjectChat.project_id == project_id,
            StudioProjectChat.chat_id == chat_id,
        )
    )
    if existing is not None:
        if existing.is_active:
            return existing, "noop_active"
        existing.is_active = True
        existing.role_in_project = role_ip
        existing.updated_at = utcnow()
        return existing, "reactivated"

    link = StudioProjectChat(
        project_id=project_id,
        chat_id=chat_id,
        role_in_project=role_ip,
        is_active=True,
    )
    try:
        async with session.begin_nested():
            session.add(link)
            await session.flush()
    except IntegrityError as exc:
        raise ValueError("bind conflict") from exc
    return link, "created"


async def unbind_chat_from_project(
    session: AsyncSession,
    *,
    project_id: UUID,
    chat_id: UUID,
) -> StudioProjectChat | None:
    row = await session.scalar(
        select(StudioProjectChat).where(
            StudioProjectChat.project_id == project_id,
            StudioProjectChat.chat_id == chat_id,
        )
    )
    if row is None:
        return None
    row.is_active = False
    row.updated_at = utcnow()
    return row


async def list_project_chats(
    session: AsyncSession,
    project_id: UUID,
    *,
    active_only: bool = True,
) -> list[StudioProjectChat]:
    stmt = select(StudioProjectChat).where(StudioProjectChat.project_id == project_id)
    if active_only:
        stmt = stmt.where(StudioProjectChat.is_active.is_(True))
    stmt = stmt.order_by(StudioProjectChat.created_at.asc())
    return list((await session.scalars(stmt)).all())
