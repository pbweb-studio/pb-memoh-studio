from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import get_session_factory
from pb_studio.knowledge.constants import (
    KnowledgeChunkEmbeddingStatus,
    KnowledgeDocumentStatus,
    KnowledgeParserName,
    KnowledgeVersionStatus,
    KNOWLEDGE_EMBEDDING_VECTOR_DIM,
)
from pb_studio.knowledge.embeddings import get_embedding_provider, redact_embedding_error
from pb_studio.knowledge.models import (
    StudioKnowledgeChunk,
    StudioKnowledgeDocument,
    StudioKnowledgeDocumentVersion,
)
from pb_studio.knowledge.parsers import parse_document_version_content
from pb_studio.knowledge.upload_io import (
    extension_from_filename,
    mime_for_extension,
    redact_kb_import_error,
    safe_upload_basename,
    save_kb_binary_upload,
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


def _cosine_distance(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 1.0
    return 1.0 - dot / (na * nb)


@dataclass(frozen=True)
class KnowledgeSearchHit:
    chunk_id: UUID
    document_id: UUID
    project_id: UUID | None
    chunk_index: int
    content_text: str
    distance: float


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


def pending_import_content_hash(document_id: UUID, version_number: int, text: str, mime: str | None) -> str:
    return content_sha256_hex(f"{document_id}\n{version_number}\n{mime or ''}\n{text}")


def upload_binary_content_hash(document_id: UUID, version_number: int, file_sha256_hex: str, mime: str | None) -> str:
    return content_sha256_hex(f"{document_id}\n{version_number}\n{mime or ''}\n{file_sha256_hex}")


async def _delete_chunks_for_version(session: AsyncSession, version_id: UUID) -> None:
    await session.execute(delete(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == version_id))


async def _finalize_parsed_version_with_plaintext(
    session: AsyncSession,
    ver: StudioKnowledgeDocumentVersion,
    document_id: UUID,
    plaintext: str,
    settings: Settings,
    *,
    parser_name: str | None,
    parser_version: str | None,
) -> None:
    await _delete_chunks_for_version(session, ver.id)
    max_chars = settings.studio_kb_chunk_max_chars
    overlap = settings.studio_kb_chunk_overlap_chars
    parts = split_text_into_chunks(plaintext, max_chars, overlap)
    for idx, chunk in enumerate(parts):
        session.add(
            StudioKnowledgeChunk(
                document_version_id=ver.id,
                chunk_index=idx,
                content_text=chunk,
                token_count=None,
                metadata_json=None,
                embedding_status=KnowledgeChunkEmbeddingStatus.PENDING,
            )
        )
    now = utcnow()
    ver.content_text = plaintext
    ver.status = KnowledgeVersionStatus.PARSED
    ver.parsed_at = now
    ver.last_error = None
    if parser_name:
        ver.parser_name = parser_name
    if parser_version:
        ver.parser_version = parser_version
    await session.flush()
    await activate_parsed_version(session, document_id, ver.id)


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
        await _finalize_parsed_version_with_plaintext(
            session,
            ver,
            document_id,
            body,
            settings,
            parser_name=parser_name or KnowledgeParserName.PLAIN,
            parser_version=parser_version or "10b",
        )
    except Exception as exc:  # noqa: BLE001
        ver.status = KnowledgeVersionStatus.FAILED
        ver.last_error = str(exc)[:4000]
        await session.flush()
        raise

    return ver, True


async def create_document_version_pending_import(
    session: AsyncSession,
    document_id: UUID,
    text: str,
    settings: Settings,
    *,
    mime_type: str | None = None,
    parser_name: str | None = None,
    parser_version: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> tuple[StudioKnowledgeDocumentVersion, bool]:
    """Create a version in pending state (no chunks) for async parse pipeline."""
    doc = await session.get(StudioKnowledgeDocument, document_id)
    if doc is None:
        raise ValueError("document not found")
    if doc.status == KnowledgeDocumentStatus.ARCHIVED:
        raise ValueError("document is archived")

    max_ver = await session.scalar(
        select(func.max(StudioKnowledgeDocumentVersion.version_number)).where(
            StudioKnowledgeDocumentVersion.document_id == document_id
        )
    )
    next_num = int(max_ver or 0) + 1
    meta = dict(metadata_json or {})
    if mime_type:
        meta["mime_type"] = mime_type

    h = pending_import_content_hash(document_id, next_num, text, mime_type)
    existing = await session.scalar(
        select(StudioKnowledgeDocumentVersion).where(
            StudioKnowledgeDocumentVersion.document_id == document_id,
            StudioKnowledgeDocumentVersion.content_hash == h,
        )
    )
    if existing is not None:
        return existing, False

    ver = StudioKnowledgeDocumentVersion(
        document_id=document_id,
        version_number=next_num,
        content_text=text,
        content_hash=h,
        parser_name=parser_name,
        parser_version=parser_version,
        status=KnowledgeVersionStatus.PENDING,
        metadata_json=meta or None,
    )
    session.add(ver)
    await session.flush()
    return ver, True


async def _create_pending_binary_version(
    session: AsyncSession,
    document_id: UUID,
    *,
    data: bytes,
    mime: str,
    original_filename: str,
    extension: str,
    settings: Settings,
) -> tuple[StudioKnowledgeDocumentVersion, bool]:
    doc = await session.get(StudioKnowledgeDocument, document_id)
    if doc is None:
        raise ValueError("document not found")
    if doc.status == KnowledgeDocumentStatus.ARCHIVED:
        raise ValueError("document is archived")

    max_ver = await session.scalar(
        select(func.max(StudioKnowledgeDocumentVersion.version_number)).where(
            StudioKnowledgeDocumentVersion.document_id == document_id
        )
    )
    next_num = int(max_ver or 0) + 1
    file_sha = hashlib.sha256(data).hexdigest()
    h = upload_binary_content_hash(document_id, next_num, file_sha, mime)
    existing = await session.scalar(
        select(StudioKnowledgeDocumentVersion).where(
            StudioKnowledgeDocumentVersion.document_id == document_id,
            StudioKnowledgeDocumentVersion.content_hash == h,
        )
    )
    if existing is not None:
        return existing, False

    rel = save_kb_binary_upload(
        settings,
        document_id=document_id,
        version_number=next_num,
        original_filename=original_filename,
        data=data,
        extension=extension,
    )
    meta: dict[str, Any] = {
        "mime_type": mime,
        "kb_storage_relpath": rel,
        "original_filename": safe_upload_basename(original_filename),
        "byte_sha256": file_sha,
    }
    ver = StudioKnowledgeDocumentVersion(
        document_id=document_id,
        version_number=next_num,
        content_text="",
        content_hash=h,
        status=KnowledgeVersionStatus.PENDING,
        metadata_json=meta,
    )
    session.add(ver)
    await session.flush()
    return ver, True


async def ingest_file_upload_to_document(
    session: AsyncSession,
    document_id: UUID,
    *,
    filename: str,
    data: bytes,
    settings: Settings,
) -> tuple[StudioKnowledgeDocumentVersion, bool]:
    ext = extension_from_filename(filename)
    if not ext:
        raise ValueError("missing file extension")
    if ext not in settings.studio_kb_allowed_extensions_set:
        raise ValueError(f"extension not allowed: {ext}")
    if len(data) > settings.studio_kb_upload_max_bytes:
        raise ValueError("file too large")

    mime = mime_for_extension(ext)

    if ext in ("txt", "md"):
        try:
            body = data.decode("utf-8")
        except UnicodeDecodeError:
            body = data.decode("utf-8", errors="replace")
        if not body.strip():
            raise ValueError("empty file")
        ver, created = await create_document_version_pending_import(
            session,
            document_id,
            body,
            settings,
            mime_type=mime,
            metadata_json={"original_filename": safe_upload_basename(filename)},
        )
    else:
        ver, created = await _create_pending_binary_version(
            session,
            document_id,
            data=data,
            mime=mime,
            original_filename=filename,
            extension=ext,
            settings=settings,
        )

    if not created:
        return ver, False

    await parse_document_version(session, ver.id, settings)
    await session.refresh(ver)
    return ver, True


async def ingest_new_document_from_upload(
    session: AsyncSession,
    *,
    title: str,
    project_id: UUID | None,
    filename: str,
    data: bytes,
    settings: Settings,
) -> tuple[StudioKnowledgeDocument, StudioKnowledgeDocumentVersion, bool]:
    ext = extension_from_filename(filename)
    if not ext or ext not in settings.studio_kb_allowed_extensions_set:
        raise ValueError(f"extension not allowed: {ext or '?'}")
    if len(data) > settings.studio_kb_upload_max_bytes:
        raise ValueError("file too large")
    meta_upload = {"upload_original_filename": safe_upload_basename(filename)}
    doc_title = (title or "").strip() or safe_upload_basename(filename)
    doc = await create_document(
        session,
        title=doc_title,
        source_type="file",
        project_id=project_id,
        metadata_json=meta_upload,
    )
    try:
        ver, created = await ingest_file_upload_to_document(
            session,
            doc.id,
            filename=filename,
            data=data,
            settings=settings,
        )
    except Exception:
        await session.delete(doc)
        await session.flush()
        raise
    return doc, ver, created


async def parse_document_version(
    session: AsyncSession,
    version_id: UUID,
    settings: Settings,
) -> StudioKnowledgeDocumentVersion:
    ver = await session.get(StudioKnowledgeDocumentVersion, version_id)
    if ver is None:
        raise ValueError("version not found")
    if ver.status == KnowledgeVersionStatus.PARSED:
        return ver

    doc = await session.get(StudioKnowledgeDocument, ver.document_id)
    if doc is None:
        raise ValueError("document not found")
    if doc.status == KnowledgeDocumentStatus.ARCHIVED:
        raise ValueError("document is archived")

    await _delete_chunks_for_version(session, ver.id)
    outcome = parse_document_version_content(document=doc, version=ver, settings=settings)

    if outcome.unsupported or not outcome.ok:
        ver.status = (
            KnowledgeVersionStatus.FAILED_UNSUPPORTED
            if outcome.unsupported
            else KnowledgeVersionStatus.FAILED
        )
        ver.last_error = redact_kb_import_error(outcome.error_message or "parse failed")[:4000]
        ver.parsed_at = None
        ver.parser_name = outcome.parser_name
        ver.parser_version = outcome.parser_version
        await session.flush()
        return ver

    try:
        await _finalize_parsed_version_with_plaintext(
            session,
            ver,
            doc.id,
            outcome.plain_text,
            settings,
            parser_name=outcome.parser_name,
            parser_version=outcome.parser_version,
        )
    except Exception as exc:  # noqa: BLE001
        ver.status = KnowledgeVersionStatus.FAILED
        ver.last_error = redact_kb_import_error(str(exc))[:4000]
        ver.parsed_at = None
        await session.flush()
        raise

    return ver


async def parse_all_pending_versions_for_document(
    session: AsyncSession,
    document_id: UUID,
    settings: Settings,
) -> dict[str, int]:
    rows = list(
        (
            await session.scalars(
                select(StudioKnowledgeDocumentVersion)
                .where(
                    StudioKnowledgeDocumentVersion.document_id == document_id,
                    StudioKnowledgeDocumentVersion.status == KnowledgeVersionStatus.PENDING,
                )
                .order_by(StudioKnowledgeDocumentVersion.version_number.asc())
            )
        ).all()
    )
    parsed = failed = 0
    for row in rows:
        try:
            updated = await parse_document_version(session, row.id, settings)
            if updated.status == KnowledgeVersionStatus.PARSED:
                parsed += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001
            failed += 1
    return {"parsed": parsed, "failed": failed}


async def list_pending_version_ids(session: AsyncSession, *, limit: int = 50) -> list[UUID]:
    lim = min(max(limit, 1), 200)
    rows = list(
        (
            await session.scalars(
                select(StudioKnowledgeDocumentVersion.id)
                .where(StudioKnowledgeDocumentVersion.status == KnowledgeVersionStatus.PENDING)
                .order_by(StudioKnowledgeDocumentVersion.created_at.asc())
                .limit(lim)
            )
        ).all()
    )
    return [r for r in rows]


async def parse_pending_knowledge_versions_batch(
    session: AsyncSession,
    settings: Settings,
    *,
    limit: int = 50,
) -> dict[str, int]:
    ids = await list_pending_version_ids(session, limit=limit)
    parsed = failed = 0
    for vid in ids:
        try:
            updated = await parse_document_version(session, vid, settings)
            if updated.status == KnowledgeVersionStatus.PARSED:
                parsed += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001
            failed += 1
    return {"parsed": parsed, "failed": failed}


async def run_parse_pending_knowledge_standalone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        out = await parse_pending_knowledge_versions_batch(session, settings, limit=50)
        await session.commit()
    return out


async def embed_pending_knowledge_chunks_batch(
    session: AsyncSession,
    settings: Settings,
    *,
    limit: int = 50,
) -> dict[str, int]:
    if not settings.studio_kb_embeddings_enabled:
        return {"embedded": 0, "failed": 0}
    lim = min(max(limit, 1), 200)
    rows = list(
        (
            await session.scalars(
                select(StudioKnowledgeChunk)
                .join(
                    StudioKnowledgeDocumentVersion,
                    StudioKnowledgeChunk.document_version_id == StudioKnowledgeDocumentVersion.id,
                )
                .join(StudioKnowledgeDocument, StudioKnowledgeDocumentVersion.document_id == StudioKnowledgeDocument.id)
                .where(
                    StudioKnowledgeChunk.embedding_status == KnowledgeChunkEmbeddingStatus.PENDING,
                    StudioKnowledgeDocumentVersion.status == KnowledgeVersionStatus.PARSED,
                    StudioKnowledgeDocument.status != KnowledgeDocumentStatus.ARCHIVED,
                )
                .order_by(StudioKnowledgeChunk.created_at.asc())
                .limit(lim)
            )
        ).all()
    )
    provider = get_embedding_provider(settings)
    bsize = max(1, min(settings.studio_kb_embedding_batch_size, 128))
    embedded = failed = 0
    secret = (settings.studio_kb_embedding_api_key or "").strip() or None

    def _apply_vec(ch: StudioKnowledgeChunk, vec: list[float]) -> None:
        if len(vec) != KNOWLEDGE_EMBEDDING_VECTOR_DIM:
            raise ValueError(f"embedding dim mismatch: got {len(vec)}, expected {KNOWLEDGE_EMBEDDING_VECTOR_DIM}")
        ch.embedding = vec
        ch.embedding_model = provider.model_label
        ch.embedded_at = utcnow()
        ch.embedding_status = KnowledgeChunkEmbeddingStatus.EMBEDDED
        ch.embedding_last_error = None

    for i in range(0, len(rows), bsize):
        batch = rows[i : i + bsize]
        if provider.batch_atomic:
            texts = [ch.content_text for ch in batch]
            try:
                vecs = await provider.embed_texts(texts)
            except Exception as exc:  # noqa: BLE001
                msg = redact_embedding_error(str(exc), secret)[:4000]
                for ch in batch:
                    if ch.embedding_status != KnowledgeChunkEmbeddingStatus.PENDING:
                        continue
                    ch.embedding_status = KnowledgeChunkEmbeddingStatus.FAILED
                    ch.embedding_last_error = msg
                    failed += 1
                await session.flush()
                continue
            for ch, vec in zip(batch, vecs, strict=True):
                if ch.embedding_status != KnowledgeChunkEmbeddingStatus.PENDING:
                    continue
                try:
                    _apply_vec(ch, vec)
                    embedded += 1
                except Exception as exc:  # noqa: BLE001
                    ch.embedding_status = KnowledgeChunkEmbeddingStatus.FAILED
                    ch.embedding_last_error = redact_embedding_error(str(exc), secret)[:4000]
                    failed += 1
                await session.flush()
        else:
            for ch in batch:
                if ch.embedding_status != KnowledgeChunkEmbeddingStatus.PENDING:
                    continue
                try:
                    vec = await provider.embed_one(ch.content_text)
                    _apply_vec(ch, vec)
                    embedded += 1
                except Exception as exc:  # noqa: BLE001
                    ch.embedding_status = KnowledgeChunkEmbeddingStatus.FAILED
                    ch.embedding_last_error = redact_embedding_error(str(exc), secret)[:4000]
                    failed += 1
                await session.flush()
    return {"embedded": embedded, "failed": failed}


async def run_embed_pending_knowledge_standalone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    if not settings.studio_kb_embeddings_enabled:
        return {"embedded": 0, "failed": 0}
    factory = get_session_factory(settings)
    async with factory() as session:
        out = await embed_pending_knowledge_chunks_batch(session, settings, limit=50)
        await session.commit()
    return out


async def _search_chunks_sqlite(
    session: AsyncSession,
    *,
    query_vec: list[float],
    project_id: UUID | None,
    top_k: int,
) -> list[KnowledgeSearchHit]:
    stmt = (
        select(StudioKnowledgeChunk, StudioKnowledgeDocument)
        .join(
            StudioKnowledgeDocumentVersion,
            StudioKnowledgeChunk.document_version_id == StudioKnowledgeDocumentVersion.id,
        )
        .join(StudioKnowledgeDocument, StudioKnowledgeDocumentVersion.document_id == StudioKnowledgeDocument.id)
        .where(
            StudioKnowledgeChunk.embedding_status == KnowledgeChunkEmbeddingStatus.EMBEDDED,
            StudioKnowledgeDocument.status != KnowledgeDocumentStatus.ARCHIVED,
        )
    )
    if project_id is not None:
        stmt = stmt.where(StudioKnowledgeDocument.project_id == project_id)
    rows = (await session.execute(stmt)).all()
    scored: list[tuple[float, StudioKnowledgeChunk, StudioKnowledgeDocument]] = []
    for chunk, doc in rows:
        emb = chunk.embedding
        if emb is None or len(emb) != KNOWLEDGE_EMBEDDING_VECTOR_DIM:
            continue
        dist = _cosine_distance(query_vec, emb)
        scored.append((dist, chunk, doc))
    scored.sort(key=lambda item: item[0])
    out: list[KnowledgeSearchHit] = []
    for dist, chunk, doc in scored[:top_k]:
        out.append(
            KnowledgeSearchHit(
                chunk_id=chunk.id,
                document_id=doc.id,
                project_id=doc.project_id,
                chunk_index=chunk.chunk_index,
                content_text=chunk.content_text,
                distance=float(dist),
            )
        )
    return out


async def _search_chunks_postgres(
    session: AsyncSession,
    *,
    query_vec: list[float],
    project_id: UUID | None,
    top_k: int,
) -> list[KnowledgeSearchHit]:
    literal = "[" + ",".join(f"{float(x):.10g}" for x in query_vec) + "]"
    base_sql = """
SELECT c.id AS chunk_id, v.document_id AS document_id, d.project_id AS project_id,
       c.chunk_index AS chunk_index, c.content_text AS content_text,
       (c.embedding <=> CAST(:qvl AS vector)) AS dist
FROM studio_knowledge_chunks c
JOIN studio_knowledge_document_versions v ON v.id = c.document_version_id
JOIN studio_knowledge_documents d ON d.id = v.document_id
WHERE c.embedding_status = 'embedded'
  AND c.embedding IS NOT NULL
  AND d.status != 'archived'
"""
    if project_id is not None:
        sql = (
            base_sql
            + " AND d.project_id = CAST(:project_id AS uuid) ORDER BY c.embedding <=> CAST(:qvl AS vector) LIMIT :lim"
        )
        params: dict[str, Any] = {"qvl": literal, "project_id": project_id, "lim": top_k}
    else:
        sql = base_sql + " ORDER BY c.embedding <=> CAST(:qvl AS vector) LIMIT :lim"
        params = {"qvl": literal, "lim": top_k}
    res = await session.execute(text(sql), params)
    hits: list[KnowledgeSearchHit] = []
    for row in res.mappings():
        hits.append(
            KnowledgeSearchHit(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                project_id=row["project_id"],
                chunk_index=int(row["chunk_index"]),
                content_text=str(row["content_text"]),
                distance=float(row["dist"]),
            )
        )
    return hits


async def search_knowledge_chunks(
    session: AsyncSession,
    settings: Settings,
    *,
    query: str,
    project_id: UUID | None = None,
    top_k: int | None = None,
) -> list[KnowledgeSearchHit]:
    if not settings.studio_kb_embeddings_enabled:
        raise ValueError("STUDIO_KB_EMBEDDINGS_ENABLED is false")
    q = (query or "").strip()
    if not q:
        raise ValueError("empty query")
    k = top_k if top_k is not None else settings.studio_kb_search_top_k
    k = min(max(k, 1), 100)
    provider = get_embedding_provider(settings)
    query_vec = await provider.embed_one(q)
    conn = await session.connection()
    if conn.dialect.name == "postgresql":
        return await _search_chunks_postgres(session, query_vec=query_vec, project_id=project_id, top_k=k)
    return await _search_chunks_sqlite(session, query_vec=query_vec, project_id=project_id, top_k=k)
