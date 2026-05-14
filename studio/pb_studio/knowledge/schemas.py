from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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
    text: str = Field(min_length=1)
    parser_name: str | None = None
    parser_version: str | None = None
    metadata_json: dict[str, Any] | None = None


class KnowledgeChunkOut(BaseModel):
    id: UUID
    document_version_id: UUID
    chunk_index: int
    content_text: str
    token_count: int | None
    metadata_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
