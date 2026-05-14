from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings
from pb_studio.knowledge.constants import (
    KnowledgeDocumentStatus,
    KnowledgeVersionStatus,
)
from pb_studio.knowledge.models import (
    StudioKnowledgeChunk,
    StudioKnowledgeDocument,
    StudioKnowledgeDocumentVersion,
)
from pb_studio.projects.models import StudioProject


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def content_sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_text_into_chunks(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Deterministic chunking by character count with trailing overlap between chunks."""
    if max_chars <= 0:
        return []
    n = len(text)
    if n == 0:
        return []
    overlap = max(0, min(overlap_chars, max_chars - 1)) if max_chars > 1 else 0
    chunks: list[str] = []
    start = 0
    while start < n:
        end = min(start + max_chars, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


async def create_document(
    session: AsyncSession,
    *,
    title: str,
    source_type: str = "manual",
    source_uri: str | None = None,
    project_id: UUID | None = None,
    metadata_json: dict[str, Any] | None = None,
    status: str = KnowledgeDocumentStatus.DRAFT,
) -> StudioKnowledgeDocument:
    if project_id is not None:
        proj = await session.get(StudioProject, project_id)
        if proj is None:
            raise ValueError("project not found")
    row = StudioKnowledgeDocument(
        title=title.strip(),
        source_type=source_type,
        source_uri=source_uri,
        project_id=project_id,
        metadata_json=metadata_json,
        status=status,
    )
    session.add(row)
    await session.flush()
    return row


async def update_document(
    session: AsyncSession,
    document_id: UUID,
    *,
    title: str | None = None,
    source_type: str | None = None,
    source_uri: str | None = None,
    project_id: UUID | None = None,
    metadata_json: dict[str, Any] | None = None,
    status: str | None = None,
) -> StudioKnowledgeDocument | None:
    row = await session.get(StudioKnowledgeDocument, document_id)
    if row is None:
        return None
    if project_id is not None:
        proj = await session.get(StudioProject, project_id)
        if proj is None:
            raise ValueError("project not found")
    if title is not None:
        row.title = title.strip()
    if source_type is not None:
        row.source_type = source_type
    if source_uri is not None:
        row.source_uri = source_uri
    if project_id is not None:
        row.project_id = project_id
    if metadata_json is not None:
        row.metadata_json = metadata_json
    if status is not None:
        row.status = status
    row.updated_at = utcnow()
    await session.flush()
    return row


async def archive_document(session: AsyncSession, document_id: UUID) -> StudioKnowledgeDocument | None:
    row = await session.get(StudioKnowledgeDocument, document_id)
    if row is None:
        return None
    now = utcnow()
    row.status = KnowledgeDocumentStatus.ARCHIVED
    row.archived_at = now
    row.updated_at = now
    await session.flush()
    return row


async def get_document(session: AsyncSession, document_id: UUID) -> StudioKnowledgeDocument | None:
    return await session.get(StudioKnowledgeDocument, document_id)


async def list_documents(
    session: AsyncSession,
    *,
    project_id: UUID | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[StudioKnowledgeDocument]:
    q = select(StudioKnowledgeDocument).order_by(StudioKnowledgeDocument.created_at.desc()).limit(limit)
    if project_id is not None:
        q = q.where(StudioKnowledgeDocument.project_id == project_id)
    if status is not None:
        q = q.where(StudioKnowledgeDocument.status == status)
    return list((await session.scalars(q)).all())


async def list_versions(session: AsyncSession, document_id: UUID) -> list[StudioKnowledgeDocumentVersion]:
    q = (
        select(StudioKnowledgeDocumentVersion)
        .where(StudioKnowledgeDocumentVersion.document_id == document_id)
        .order_by(StudioKnowledgeDocumentVersion.version_number.asc())
    )
    return list((await session.scalars(q)).all())


async def list_chunks(session: AsyncSession, version_id: UUID) -> list[StudioKnowledgeChunk]:
    q = (
        select(StudioKnowledgeChunk)
        .where(StudioKnowledgeChunk.document_version_id == version_id)
        .order_by(StudioKnowledgeChunk.chunk_index.asc())
    )
    return list((await session.scalars(q)).all())


async def activate_parsed_version(
    session: AsyncSession,
    document_id: UUID,
    version_id: UUID,
) -> StudioKnowledgeDocument | None:
    doc = await session.get(StudioKnowledgeDocument, document_id)
    ver = await session.get(StudioKnowledgeDocumentVersion, version_id)
    if doc is None or ver is None or ver.document_id != document_id:
        return None
    if ver.status != KnowledgeVersionStatus.PARSED:
        raise ValueError("version is not parsed")
    meta = dict(doc.metadata_json or {})
    meta["active_version_id"] = str(ver.id)
    doc.metadata_json = meta
    if doc.status == KnowledgeDocumentStatus.DRAFT:
        doc.status = KnowledgeDocumentStatus.ACTIVE
    doc.updated_at = utcnow()
    await session.flush()
    return doc


async def create_document_version_from_text(
    session: AsyncSession,
    document_id: UUID,
    text: str,
    settings: Settings,
    *,
    parser_name: str | None = None,
    parser_version: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> tuple[StudioKnowledgeDocumentVersion, bool]:
    """
    Create a new version from full text, split into chunks.
    Returns (version, created_new) — created_new False if same content_hash already existed for this document.
    """
    doc = await session.get(StudioKnowledgeDocument, document_id)
    if doc is None:
        raise ValueError("document not found")
    if doc.status == KnowledgeDocumentStatus.ARCHIVED:
        raise ValueError("document is archived")
    body = text
    if not body.strip():
        raise ValueError("empty text")

    h = content_sha256_hex(body)
    existing = await session.scalar(
        select(StudioKnowledgeDocumentVersion).where(
            StudioKnowledgeDocumentVersion.document_id == document_id,
            StudioKnowledgeDocumentVersion.content_hash == h,
        )
    )
    if existing is not None:
        return existing, False

    max_ver = await session.scalar(
        select(func.max(StudioKnowledgeDocumentVersion.version_number)).where(
            StudioKnowledgeDocumentVersion.document_id == document_id
        )
    )
    next_num = int(max_ver or 0) + 1

    max_chars = settings.studio_kb_chunk_max_chars
    overlap = settings.studio_kb_chunk_overlap_chars

    ver = StudioKnowledgeDocumentVersion(
        document_id=document_id,
        version_number=next_num,
        content_text=body,
        content_hash=h,
        parser_name=parser_name,
        parser_version=parser_version,
        status=KnowledgeVersionStatus.PENDING,
        metadata_json=metadata_json,
    )
    session.add(ver)
    await session.flush()

    try:
        parts = split_text_into_chunks(body, max_chars, overlap)
        for idx, chunk in enumerate(parts):
            session.add(
                StudioKnowledgeChunk(
                    document_version_id=ver.id,
                    chunk_index=idx,
                    content_text=chunk,
                    token_count=None,
                    metadata_json=None,
                )
            )
        now = utcnow()
        ver.status = KnowledgeVersionStatus.PARSED
        ver.parsed_at = now
        ver.last_error = None
        await session.flush()
        await activate_parsed_version(session, document_id, ver.id)
    except Exception as exc:  # noqa: BLE001
        ver.status = KnowledgeVersionStatus.FAILED
        ver.last_error = str(exc)[:4000]
        await session.flush()
        raise

    return ver, True
