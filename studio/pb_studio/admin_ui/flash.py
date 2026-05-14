from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import RedirectResponse


def _clip_flash(text: str, max_chars: int = 450) -> str:
    t = text.replace("\n", " ").replace("\r", "").strip()
    if len(t) > max_chars:
        return t[: max_chars - 1] + "…"
    return t


def redirect_with_flash(
    path: str,
    *,
    success: str | None = None,
    error: str | None = None,
    status_code: int = 303,
) -> RedirectResponse:
    """PRG flash via query params fs / fe (URL-encoded). No secrets — caller must sanitize."""
    q: list[str] = []
    if success:
        q.append(f"fs={quote(_clip_flash(success), safe='')}")
    if error:
        q.append(f"fe={quote(_clip_flash(error), safe='')}")
    url = f"{path}?{'&'.join(q)}" if q else path
    return RedirectResponse(url=url, status_code=status_code)
