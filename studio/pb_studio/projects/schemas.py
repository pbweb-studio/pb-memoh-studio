from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=8000)
    metadata_json: dict[str, Any] | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=8000)
    metadata_json: dict[str, Any] | None = None


class ProjectOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    slug: str
    name: str
    description: str | None
    status: str
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ProjectChatBindBody(BaseModel):
    chat_id: UUID
    role_in_project: str = Field(default="secondary", max_length=32)


class ProjectChatUnbindBody(BaseModel):
    chat_id: UUID


class ProjectChatOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    chat_id: UUID
    role_in_project: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
