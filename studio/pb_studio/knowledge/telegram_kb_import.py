"""KB import from Telegram document messages mirrored in Studio (phase 10g)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings
from pb_studio.event_mirror.models import StudioMessage
from pb_studio.knowledge.telegram_file_download import telegram_fetch_file_bytes
from pb_studio.knowledge.upload_io import extension_from_filename


def synthetic_filename_from_document(doc: dict[str, Any]) -> str:
    fn = doc.get("file_name")
    if isinstance(fn, str) and fn.strip():
        return fn.strip()
    mime = doc.get("mime_type")
    if mime == "application/pdf":
        return "telegram.pdf"
    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        return "telegram.docx"
    if mime in ("text/plain",):
        return "telegram.txt"
    if mime in ("text/markdown",):
        return "telegram.md"
    return "telegram.bin"


def telegram_document_file_id(doc: dict[str, Any]) -> str | None:
    fid = doc.get("file_id")
    if isinstance(fid, str) and fid.strip():
        return fid.strip()
    return None


async def find_last_user_document_message_before(
    session: AsyncSession,
    *,
    control_group_studio_chat_id: UUID,
    before_telegram_message_id: int,
    sender_telegram_user_id: int,
) -> tuple[StudioMessage, dict[str, Any]] | None:
    """Последнее сообщение с полем document от того же user, строго раньше команды по message_id."""
    stmt = (
        select(StudioMessage)
        .where(
            StudioMessage.chat_id == control_group_studio_chat_id,
            StudioMessage.telegram_message_id < before_telegram_message_id,
        )
        .order_by(StudioMessage.telegram_message_id.desc())
        .limit(50)
    )
    rows = list((await session.scalars(stmt)).all())
    for msg in rows:
        raw = msg.raw_message or {}
        doc = raw.get("document")
        if not isinstance(doc, dict):
            continue
        from_u = raw.get("from")
        if not isinstance(from_u, dict) or from_u.get("is_bot"):
            continue
        uid = from_u.get("id")
        if not isinstance(uid, int) or uid != sender_telegram_user_id:
            continue
        return msg, doc
    return None


async def fetch_document_bytes_for_kb(
    settings: Settings,
    *,
    file_id: str,
) -> tuple[bool, bytes | None, str, str]:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return False, None, "telegram_bot_token_missing", "telegram.bin"
    timeout_s = max(0.5, settings.studio_kb_telegram_download_timeout_ms / 1000.0)
    max_b = settings.studio_kb_telegram_effective_max_bytes
    return await telegram_fetch_file_bytes(
        token,
        file_id,
        timeout_seconds=timeout_s,
        max_bytes=max_b,
    )


def extension_allowed_for_telegram_import(filename: str, settings: Settings) -> tuple[str | None, str | None]:
    """Returns (ext, error) — ext set if ok."""
    ext = extension_from_filename(filename)
    if not ext:
        return None, "missing_extension"
    if ext not in settings.studio_kb_allowed_extensions_set:
        return None, f"extension_not_allowed:{ext}"
    return ext, None


def telegram_declared_file_size(doc: dict[str, Any]) -> int | None:
    fs = doc.get("file_size")
    return int(fs) if isinstance(fs, int) else None
