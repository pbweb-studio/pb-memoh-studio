"""Helpers for KB file uploads (phase 10f): extensions, MIME, safe names, error redaction."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from uuid import UUID

from pb_studio.core.config import Settings


def extension_from_filename(filename: str) -> str:
    name = (filename or "").strip().lower()
    if not name or name.endswith("/") or name.endswith("\\"):
        return ""
    base = Path(name).name
    if "." not in base:
        return ""
    return base.rsplit(".", 1)[-1].strip().lower()


def mime_for_extension(ext: str) -> str:
    e = (ext or "").strip().lower().lstrip(".")
    if e in ("txt", "text"):
        return "text/plain"
    if e in ("md", "markdown"):
        return "text/markdown"
    if e == "pdf":
        return "application/pdf"
    if e == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"


def safe_upload_basename(filename: str, *, max_len: int = 120) -> str:
    base = Path((filename or "upload").strip()).name
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE).strip("._") or "upload"
    if len(base) > max_len:
        base = base[:max_len]
    return base


def redact_kb_import_error(message: str) -> str:
    """Avoid leaking absolute paths / tokens in version.last_error."""
    s = (message or "").strip()
    if not s:
        return "import failed"
    s = re.sub(r"(?i)(sk-[a-z0-9]{10,})", "***API_KEY***", s)
    s = re.sub(r"(?i)(bearer\s+[a-z0-9._\-/+]{8,})", "Bearer ***", s)
    s = re.sub(r"(/[\w.\-]+){2,}", "/***PATH***", s)
    if len(s) > 2000:
        s = s[:2000] + "…"
    return s


def save_kb_binary_upload(
    settings: Settings,
    *,
    document_id: UUID,
    version_number: int,
    original_filename: str,
    data: bytes,
    extension: str,
) -> str:
    """
    Persist bytes under STUDIO_KB_STORAGE_DIR / {document_id} / {uuid}.{ext}.
    Returns POSIX-style relative path stored in version.metadata_json['kb_storage_relpath'].
    """
    root = settings.studio_kb_storage_path
    root.mkdir(parents=True, exist_ok=True)
    ext = extension.lstrip(".").lower() or "bin"
    fname = f"v{version_number}_{uuid.uuid4().hex}.{ext}"
    rel = Path(str(document_id)) / fname
    full = (root / rel).resolve()
    root_res = root.resolve()
    if not (str(full).startswith(str(root_res) + os.sep) or full == root_res):
        raise ValueError("invalid storage path")
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return rel.as_posix()
