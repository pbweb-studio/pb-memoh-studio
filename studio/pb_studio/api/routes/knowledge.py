from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pb_studio.api.deps import DbSession, verify_admin_optional, verify_kb_enabled
from pb_studio.core.config import get_settings
from pb_studio.knowledge.models import StudioKnowledgeDocumentVersion
from pb_studio.knowledge.schemas import (
    KnowledgeChunkOut,
    KnowledgeDocumentCreate,
    KnowledgeDocumentOut,
    KnowledgeDocumentPatch,
    KnowledgeVersionOut,
    KnowledgeVersionTextBody,
)
from pb_studio.knowledge import service as kb_service

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(verify_admin_optional), Depends(verify_kb_enabled)],
)


@router.get("/documents", response_model=list[KnowledgeDocumentOut])
async def get_knowledge_documents(
    session: DbSession,
    project_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[KnowledgeDocumentOut]:
    rows = await kb_service.list_documents(session, project_id=project_id, status=status_filter, limit=limit)
    return [KnowledgeDocumentOut.model_validate(r) for r in rows]


@router.post("/documents", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED)
async def post_knowledge_document(session: DbSession, body: KnowledgeDocumentCreate) -> KnowledgeDocumentOut:
    try:
        row = await kb_service.create_document(
            session,
            title=body.title,
            source_type=body.source_type,
            source_uri=body.source_uri,
            project_id=body.project_id,
            metadata_json=body.metadata_json,
            status=body.status,
        )
        return KnowledgeDocumentOut.model_validate(row)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentOut)
async def get_knowledge_document(session: DbSession, document_id: UUID) -> KnowledgeDocumentOut:
    row = await kb_service.get_document(session, document_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    return KnowledgeDocumentOut.model_validate(row)


@router.patch("/documents/{document_id}", response_model=KnowledgeDocumentOut)
async def patch_knowledge_document(
    session: DbSession, document_id: UUID, body: KnowledgeDocumentPatch
) -> KnowledgeDocumentOut:
    updates = body.model_dump(exclude_unset=True)
    try:
        row = await kb_service.update_document(session, document_id, **updates)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    return KnowledgeDocumentOut.model_validate(row)


@router.post("/documents/{document_id}/archive", response_model=KnowledgeDocumentOut)
async def post_knowledge_document_archive(session: DbSession, document_id: UUID) -> KnowledgeDocumentOut:
    row = await kb_service.archive_document(session, document_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    return KnowledgeDocumentOut.model_validate(row)


@router.post("/documents/{document_id}/versions/text", response_model=KnowledgeVersionOut)
async def post_knowledge_document_version_text(
    session: DbSession, document_id: UUID, body: KnowledgeVersionTextBody
) -> KnowledgeVersionOut:
    settings = get_settings()
    try:
        ver, _created = await kb_service.create_document_version_from_text(
            session,
            document_id,
            body.text,
            settings,
            parser_name=body.parser_name,
            parser_version=body.parser_version,
            metadata_json=body.metadata_json,
        )
        return KnowledgeVersionOut.model_validate(ver)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/documents/{document_id}/versions", response_model=list[KnowledgeVersionOut])
async def get_knowledge_document_versions(session: DbSession, document_id: UUID) -> list[KnowledgeVersionOut]:
    doc = await kb_service.get_document(session, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    rows = await kb_service.list_versions(session, document_id)
    return [KnowledgeVersionOut.model_validate(r) for r in rows]


@router.get("/versions/{version_id}/chunks", response_model=list[KnowledgeChunkOut])
async def get_knowledge_version_chunks(session: DbSession, version_id: UUID) -> list[KnowledgeChunkOut]:
    ver = await session.get(StudioKnowledgeDocumentVersion, version_id)
    if ver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")
    rows = await kb_service.list_chunks(session, version_id)
    return [KnowledgeChunkOut.model_validate(r) for r in rows]
