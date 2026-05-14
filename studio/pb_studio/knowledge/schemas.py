from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    source_type: str = "manual"
    source_uri: str | None = None
    project_id: UUID | None = None
    metadata_json: dict[str, Any] | None = None
    status: str = "draft"


class KnowledgeDocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    source_type: str | None = None
    source_uri: str | None = None
    project_id: UUID | None = None
    metadata_json: dict[str, Any] | None = None
    status: str | None = None


class KnowledgeDocumentOut(BaseModel):
    id: UUID
    title: str
    source_type: str
    source_uri: str | None
    status: str
    project_id: UUID | None
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    last_error: str | None

    model_config = {"from_attributes": True}


class KnowledgeVersionOut(BaseModel):
    id: UUID
    document_id: UUID
    version_number: int
    content_hash: str
    parser_name: str | None
    parser_version: str | None
    status: str
    metadata_json: dict[str, Any] | None
    created_at: datetime
    parsed_at: datetime | None
    last_error: str | None

    model_config = {"from_attributes": True}


class KnowledgeVersionTextBody(BaseModel):
    text: str = ""
    defer_parse: bool = False
    parser_name: str | None = None
    parser_version: str | None = None
    metadata_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_text_or_defer(self) -> KnowledgeVersionTextBody:
        if not self.defer_parse and not (self.text or "").strip():
            raise ValueError("text must be non-empty unless defer_parse is true")
        return self


class KnowledgeParseBatchOut(BaseModel):
    parsed: int
    failed: int


class KnowledgeEmbedBatchOut(BaseModel):
    embedded: int
    failed: int


class KnowledgeSearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    project_id: UUID | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)


class KnowledgeSearchHitOut(BaseModel):
    chunk_id: UUID
    document_id: UUID
    project_id: UUID | None
    chunk_index: int
    content_text: str
    distance: float


class KnowledgeChunkOut(BaseModel):
    id: UUID
    document_version_id: UUID
    chunk_index: int
    content_text: str
    token_count: int | None
    metadata_json: dict[str, Any] | None
    created_at: datetime
    embedding_status: str | None = None
    embedding_model: str | None = None
    embedded_at: datetime | None = None
    embedding_last_error: str | None = None

    model_config = {"from_attributes": True}
