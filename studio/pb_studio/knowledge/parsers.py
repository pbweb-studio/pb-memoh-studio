from __future__ import annotations

from dataclasses import dataclass

from pb_studio.knowledge.constants import KnowledgeParserName
from pb_studio.knowledge.models import StudioKnowledgeDocument, StudioKnowledgeDocumentVersion


# MIME types we only flag as unsupported in 10b (no Docling / binary parsers).
UNSUPPORTED_MIMES = frozenset(
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


def parse_document_version_content(
    *,
    document: StudioKnowledgeDocument,
    version: StudioKnowledgeDocumentVersion,
) -> ParseOutcome:
    """
    Parser abstraction for 10b: plain text / markdown in-process; PDF/DOCX → failed_unsupported.
    No external I/O.
    """
    mime = effective_mime(document, version)
    if mime in UNSUPPORTED_MIMES:
        return ParseOutcome(
            ok=False,
            plain_text="",
            parser_name=KnowledgeParserName.PLACEHOLDER,
            parser_version="10b",
            unsupported=True,
            error_message=f"unsupported mime for studio parser: {mime}",
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

    # Unknown non-text: treat as unsupported (safe default).
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
