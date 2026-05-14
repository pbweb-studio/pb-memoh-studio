"""Optional Docling conversion for PDF/DOCX (phase 10f)."""

from __future__ import annotations

from pathlib import Path

from pb_studio.core.config import Settings
from pb_studio.knowledge.upload_io import redact_kb_import_error


def docling_import_available() -> bool:
    try:
        import docling  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


def convert_office_file_to_markdown(local_path: Path, settings: Settings) -> str:
    """
    Run Docling on a local file. Caller must ensure studio_kb_docling_enabled and docling_import_available().
    """
    del settings  # reserved for future timeouts / options
    from docling.document_converter import DocumentConverter  # noqa: PLC0415

    path = Path(local_path)
    if not path.is_file():
        raise FileNotFoundError("upload file missing on disk")

    converter = DocumentConverter()
    result = converter.convert(str(path))
    return (result.document.export_to_markdown() or "").strip()


def convert_upload_path_to_markdown(full_path: Path, settings: Settings) -> str:
    try:
        return convert_office_file_to_markdown(full_path, settings)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(redact_kb_import_error(str(exc))) from exc
