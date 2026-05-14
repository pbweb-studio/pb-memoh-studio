from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pb_studio.response_queue.models import Base, JSONCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudioKnowledgeDocument(Base):
    __tablename__ = "studio_knowledge_documents"
    __table_args__ = (
        Index("ix_studio_knowledge_documents_project_id", "project_id"),
        Index("ix_studio_knowledge_documents_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    source_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("studio_projects.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    versions: Mapped[list["StudioKnowledgeDocumentVersion"]] = relationship(
        "StudioKnowledgeDocumentVersion", back_populates="document", cascade="all, delete-orphan"
    )


class StudioKnowledgeDocumentVersion(Base):
    __tablename__ = "studio_knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_studio_kb_doc_versions_doc_ver"),
        UniqueConstraint("document_id", "content_hash", name="uq_studio_kb_doc_versions_doc_hash"),
        Index("ix_studio_knowledge_document_versions_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    parser_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    document: Mapped["StudioKnowledgeDocument"] = relationship("StudioKnowledgeDocument", back_populates="versions")
    chunks: Mapped[list["StudioKnowledgeChunk"]] = relationship(
        "StudioKnowledgeChunk", back_populates="document_version", cascade="all, delete-orphan"
    )


class StudioKnowledgeChunk(Base):
    __tablename__ = "studio_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_index", name="uq_studio_kb_chunks_ver_idx"),
        Index("ix_studio_knowledge_chunks_document_version_id", "document_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio_knowledge_document_versions.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONCompat, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document_version: Mapped["StudioKnowledgeDocumentVersion"] = relationship(
        "StudioKnowledgeDocumentVersion", back_populates="chunks"
    )
