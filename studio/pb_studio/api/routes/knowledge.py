from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from pb_studio.api.deps import (
    DbSession,
    verify_admin_optional,
    verify_kb_embeddings_enabled,
    verify_kb_enabled,
    verify_kb_rag_enabled,
)
from pb_studio.core.config import get_settings
from pb_studio.knowledge.models import StudioKnowledgeDocumentVersion
from pb_studio.knowledge.rag import ask_knowledge_base
from pb_studio.knowledge.schemas import (
    KnowledgeAskBody,
    KnowledgeAskOut,
    KnowledgeChunkOut,
    KnowledgeDocumentCreate,
    KnowledgeDocumentOut,
    KnowledgeDocumentPatch,
    KnowledgeEmbedBatchOut,
    KnowledgeParseBatchOut,
    KnowledgeSearchBody,
    KnowledgeSearchHitOut,
    KnowledgeUploadOut,
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


@router.post("/documents/upload", response_model=KnowledgeUploadOut, status_code=status.HTTP_201_CREATED)
async def post_knowledge_documents_upload(
    session: DbSession,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    project_id: UUID | None = Form(default=None),
) -> KnowledgeUploadOut:
    settings = get_settings()
    raw_name = file.filename or "upload"
    data = await file.read()
    if len(data) > settings.studio_kb_upload_max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="file too large")
    try:
        doc, ver, _created = await kb_service.ingest_new_document_from_upload(
            session,
            title=(title or "").strip(),
            project_id=project_id,
            filename=raw_name,
            data=data,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.refresh(doc)
    await session.refresh(ver)
    return KnowledgeUploadOut(
        document=KnowledgeDocumentOut.model_validate(doc),
        version=KnowledgeVersionOut.model_validate(ver),
    )


@router.post("/documents/{document_id}/versions/upload", response_model=KnowledgeUploadOut, status_code=status.HTTP_201_CREATED)
async def post_knowledge_document_version_upload(
    session: DbSession,
    document_id: UUID,
    file: UploadFile = File(...),
) -> KnowledgeUploadOut:
    settings = get_settings()
    raw_name = file.filename or "upload"
    data = await file.read()
    if len(data) > settings.studio_kb_upload_max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="file too large")
    try:
        ver, _created = await kb_service.ingest_file_upload_to_document(
            session,
            document_id,
            filename=raw_name,
            data=data,
            settings=settings,
        )
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_404_NOT_FOUND if msg == "document not found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, detail=msg) from exc
    doc = await kb_service.get_document(session, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    await session.refresh(ver)
    return KnowledgeUploadOut(
        document=KnowledgeDocumentOut.model_validate(doc),
        version=KnowledgeVersionOut.model_validate(ver),
    )


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
    mime_type = None
    if body.metadata_json:
        mime_type = body.metadata_json.get("mime_type")
        if mime_type is not None:
            mime_type = str(mime_type)
    try:
        if body.defer_parse:
            ver, _created = await kb_service.create_document_version_pending_import(
                session,
                document_id,
                body.text,
                settings,
                mime_type=mime_type,
                parser_name=body.parser_name,
                parser_version=body.parser_version,
                metadata_json=body.metadata_json,
            )
        else:
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


@router.post("/documents/{document_id}/parse", response_model=KnowledgeParseBatchOut)
async def post_knowledge_document_parse(session: DbSession, document_id: UUID) -> KnowledgeParseBatchOut:
    settings = get_settings()
    doc = await kb_service.get_document(session, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    try:
        out = await kb_service.parse_all_pending_versions_for_document(session, document_id, settings)
        return KnowledgeParseBatchOut.model_validate(out)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/parse-pending", response_model=KnowledgeParseBatchOut)
async def post_knowledge_parse_pending(session: DbSession) -> KnowledgeParseBatchOut:
    settings = get_settings()
    out = await kb_service.parse_pending_knowledge_versions_batch(session, settings, limit=50)
    return KnowledgeParseBatchOut.model_validate(out)


@router.post(
    "/embed-pending",
    response_model=KnowledgeEmbedBatchOut,
    dependencies=[Depends(verify_kb_embeddings_enabled)],
)
async def post_knowledge_embed_pending(session: DbSession) -> KnowledgeEmbedBatchOut:
    settings = get_settings()
    out = await kb_service.embed_pending_knowledge_chunks_batch(session, settings, limit=50)
    return KnowledgeEmbedBatchOut.model_validate(out)


@router.post(
    "/search",
    response_model=list[KnowledgeSearchHitOut],
    dependencies=[Depends(verify_kb_embeddings_enabled)],
)
async def post_knowledge_search(session: DbSession, body: KnowledgeSearchBody) -> list[KnowledgeSearchHitOut]:
    settings = get_settings()
    try:
        hits = await kb_service.search_knowledge_chunks(
            session,
            settings,
            query=body.query,
            project_id=body.project_id,
            top_k=body.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [
        KnowledgeSearchHitOut(
            chunk_id=h.chunk_id,
            document_id=h.document_id,
            project_id=h.project_id,
            chunk_index=h.chunk_index,
            content_text=h.content_text,
            distance=h.distance,
        )
        for h in hits
    ]


@router.post(
    "/ask",
    response_model=KnowledgeAskOut,
    dependencies=[Depends(verify_kb_rag_enabled)],
)
async def post_knowledge_ask(session: DbSession, body: KnowledgeAskBody) -> KnowledgeAskOut:
    settings = get_settings()
    try:
        result = await ask_knowledge_base(
            session,
            settings,
            question=body.question,
            project_id=body.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return KnowledgeAskOut(
        answer=result.answer,
        sources=[
            KnowledgeSearchHitOut(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                project_id=h.project_id,
                chunk_index=h.chunk_index,
                content_text=h.content_text,
                distance=h.distance,
            )
            for h in result.sources
        ],
    )


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
