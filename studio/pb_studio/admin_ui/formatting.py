"""Display helpers for Studio Admin HTML (no secrets)."""

from __future__ import annotations

from datetime import datetime, timezone


def format_admin_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M UTC")


def snip_text(text: str | None, max_len: int = 72) -> str:
    if not text:
        return ""
    t = text.replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"
