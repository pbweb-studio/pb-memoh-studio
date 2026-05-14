from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pb_studio.core.config import Settings, get_settings
from pb_studio.knowledge.constants import KnowledgeParserName
from pb_studio.knowledge.docling_convert import (
    convert_upload_path_to_markdown,
    docling_import_available,
)
from pb_studio.knowledge.models import StudioKnowledgeDocument, StudioKnowledgeDocumentVersion


# MIME types that require Docling/binary pipeline when content is on disk (phase 10f).
BINARY_KB_MIMES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }
)

MARKDOWN_MIMES = frozenset({"text/markdown", "text/x-markdown"})


@dataclass
class ParseOutcome:
    ok: bool
    plain_text: str
    parser_name: str
    parser_version: str
    unsupported: bool = False
    error_message: str | None = None


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def effective_mime(
    document: StudioKnowledgeDocument,
    version: StudioKnowledgeDocumentVersion,
) -> str:
    meta = version.metadata_json or {}
    raw = meta.get("mime_type") or meta.get("content_type")
    if isinstance(raw, str) and raw.strip():
        return raw.split(";")[0].strip().lower()
    if document.source_type in ("file", "url", "google_drive", "telegram"):
        return ""
    return "text/plain"


def _resolve_kb_storage_file(settings: Settings, relpath: str) -> Path:
    root = settings.studio_kb_storage_path
    rel = Path(relpath)
    if rel.is_absolute():
        raise ValueError("kb_storage_relpath must be relative")
    full = (root / rel).resolve()
    root_res = root.resolve()
    if not (str(full).startswith(str(root_res) + os.sep) or full == root_res):
        raise ValueError("kb storage path outside root")
    return full


def parse_document_version_content(
    *,
    document: StudioKnowledgeDocument,
    version: StudioKnowledgeDocumentVersion,
    settings: Settings | None = None,
) -> ParseOutcome:
    """
    Parser: plain text / markdown; PDF/DOCX via Docling when enabled + file on disk.
    """
    settings = settings or get_settings()
    mime = effective_mime(document, version)
    meta = version.metadata_json or {}
    storage_rel = meta.get("kb_storage_relpath")
    if isinstance(storage_rel, str) and storage_rel.strip() and mime in BINARY_KB_MIMES:
        if not settings.studio_kb_docling_enabled:
            return ParseOutcome(
                ok=False,
                plain_text="",
                parser_name=KnowledgeParserName.PLACEHOLDER,
                parser_version="10f",
                unsupported=True,
                error_message="docling disabled (STUDIO_KB_DOCLING_ENABLED=false)",
            )
        if not docling_import_available():
            return ParseOutcome(
                ok=False,
                plain_text="",
                parser_name=KnowledgeParserName.PLACEHOLDER,
                parser_version="10f",
                unsupported=True,
                error_message="docling python package not installed",
            )
        try:
            full = _resolve_kb_storage_file(settings, storage_rel.strip())
            md = convert_upload_path_to_markdown(full, settings)
            if not md.strip():
                return ParseOutcome(
                    ok=False,
                    plain_text="",
                    parser_name=KnowledgeParserName.DOCLING,
                    parser_version="10f",
                    unsupported=False,
                    error_message="docling produced empty text",
                )
            return ParseOutcome(
                ok=True,
                plain_text=_normalize_line_endings(md),
                parser_name=KnowledgeParserName.DOCLING,
                parser_version="10f",
            )
        except Exception as exc:  # noqa: BLE001
            from pb_studio.knowledge.upload_io import redact_kb_import_error

            return ParseOutcome(
                ok=False,
                plain_text="",
                parser_name=KnowledgeParserName.DOCLING,
                parser_version="10f",
                unsupported=False,
                error_message=redact_kb_import_error(str(exc))[:4000],
            )

    # Legacy 10b: PDF/DOCX in DB as text-only pending rows (no file) → unsupported.
    if mime in BINARY_KB_MIMES and not storage_rel:
        return ParseOutcome(
            ok=False,
            plain_text="",
            parser_name=KnowledgeParserName.PLACEHOLDER,
            parser_version="10b",
            unsupported=True,
            error_message=f"unsupported mime for studio parser (no upload file): {mime}",
        )

    raw = version.content_text
    if raw is None:
        raw = ""
    text = _normalize_line_endings(raw)

    if mime in MARKDOWN_MIMES or mime.endswith("+markdown"):
        return ParseOutcome(
            ok=True,
            plain_text=text,
            parser_name=KnowledgeParserName.MARKDOWN,
            parser_version="10b",
        )

    if mime in ("", "text/plain") or mime.startswith("text/"):
        return ParseOutcome(
            ok=True,
            plain_text=text,
            parser_name=KnowledgeParserName.PLAIN,
            parser_version="10b",
        )

    if mime and not mime.startswith("text/"):
        return ParseOutcome(
            ok=False,
            plain_text="",
            parser_name=KnowledgeParserName.PLACEHOLDER,
            parser_version="10b",
            unsupported=True,
            error_message=f"unsupported mime for studio parser: {mime}",
        )

    return ParseOutcome(
        ok=True,
        plain_text=text,
        parser_name=KnowledgeParserName.PLAIN,
        parser_version="10b",
    )
