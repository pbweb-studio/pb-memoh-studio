from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.responses import RedirectResponse

from pb_studio.core.config import Settings, get_settings

COOKIE_NAME = "studio_admin_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7


class AdminAuthRedirect(Exception):
    """Internal: trigger redirect to login (handled by exception_handler)."""

    def __init__(self, location: str) -> None:
        self.location = location


def admin_auth_redirect_handler(_request: Request, exc: AdminAuthRedirect) -> RedirectResponse:
    return RedirectResponse(url=exc.location, status_code=status.HTTP_302_FOUND)


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    token = (settings.studio_admin_token or "").strip()
    if not token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_ADMIN_TOKEN is not configured",
        )
    return URLSafeTimedSerializer(secret_key=token, salt="pb-studio-admin-ui-v1")


def issue_session_cookie(settings: Settings) -> str:
    return _serializer(settings).dumps({"ok": True})


def verify_session_cookie(settings: Settings, raw: str | None) -> bool:
    if not raw:
        return False
    try:
        data = _serializer(settings).loads(raw, max_age=SESSION_MAX_AGE)
        return isinstance(data, dict) and data.get("ok") is True
    except (BadSignature, SignatureExpired, TypeError):
        return False


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    return auth.removeprefix("Bearer ").strip()


def require_admin_ui(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Cookie session or Authorization Bearer. Token is never logged."""
    token = (settings.studio_admin_token or "").strip()
    if not token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STUDIO_ADMIN_TOKEN is not configured",
        )
    bearer = _bearer_token(request)
    if bearer is not None:
        if bearer != token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
        return
    if verify_session_cookie(settings, request.cookies.get(COOKIE_NAME)):
        return
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept or accept.strip() in ("", "*/*"):
        next_url = str(request.url.path)
        if request.url.query:
            next_url += f"?{request.url.query}"
        from urllib.parse import quote

        loc = "/admin/login"
        if next_url and next_url not in ("/admin/login", "/admin/login/"):
            loc = f"/admin/login?next={quote(next_url, safe='')}"
        raise AdminAuthRedirect(loc)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def redirect_if_logged_in(request: Request, settings: Settings) -> RedirectResponse | None:
    token = (settings.studio_admin_token or "").strip()
    if not token:
        return None
    if _bearer_token(request) == token:
        return RedirectResponse("/admin/", status_code=302)
    if verify_session_cookie(settings, request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/admin/", status_code=302)
    return None
