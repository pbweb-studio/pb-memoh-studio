from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pb_studio.core.config import get_settings
from pb_studio.mcp_tools import handlers as mcp_handlers


def _wrap_bearer(app: Callable[..., Awaitable[None]], token: str) -> Callable[..., Awaitable[None]]:
    """Require Authorization: Bearer <token> when token is non-empty."""

    async def middleware(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await app(scope, receive, send)
            return
        want = f"Bearer {token}"
        raw_headers = scope.get("headers") or []
        hdr = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in raw_headers}
        if hdr.get("authorization", "") != want:
            body = json.dumps({"detail": "unauthorized"}).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [[b"content-type", b"application/json; charset=utf-8"]],
                }
            )
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return
        await app(scope, receive, send)

    return middleware


def build_mcp_asgi_app() -> Callable[..., Awaitable[None]]:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("pb-studio")

    @mcp.tool()
    async def studio_list_chats(include_debug: bool = False) -> str:
        return await mcp_handlers.studio_list_chats(include_debug=include_debug)

    @mcp.tool()
    async def studio_get_report(period: str = "today", include_debug: bool = False) -> str:
        return await mcp_handlers.studio_get_report(period=period, include_debug=include_debug)

    @mcp.tool()
    async def studio_list_open_sla(include_debug: bool = False) -> str:
        return await mcp_handlers.studio_list_open_sla(include_debug=include_debug)

    @mcp.tool()
    async def studio_list_projects(include_debug: bool = False) -> str:
        return await mcp_handlers.studio_list_projects(include_debug=include_debug)

    @mcp.tool()
    async def studio_get_project_digest(
        project_name_guess: str,
        period: str = "today",
        include_debug: bool = False,
    ) -> str:
        return await mcp_handlers.studio_get_project_digest(
            project_name_guess, period=period, include_debug=include_debug
        )

    @mcp.tool()
    async def studio_search_kb(query: str, include_debug: bool = False) -> str:
        return await mcp_handlers.studio_search_kb(query, include_debug=include_debug)

    @mcp.tool()
    async def studio_get_kb_sources(limit: int = 30, include_debug: bool = False) -> str:
        return await mcp_handlers.studio_get_kb_sources(limit=limit, include_debug=include_debug)

    @mcp.tool()
    async def studio_save_behavior_rule(
        rule_text: str,
        scope: str = "global",
        project_slug: str | None = None,
        studio_chat_id: str | None = None,
    ) -> str:
        return await mcp_handlers.studio_save_behavior_rule(
            rule_text, scope=scope, project_slug=project_slug, studio_chat_id=studio_chat_id
        )

    @mcp.tool()
    async def studio_save_memory_item(
        text: str,
        scope_type: str = "global",
        project_slug: str | None = None,
    ) -> str:
        return await mcp_handlers.studio_save_memory_item(text, scope_type=scope_type, project_slug=project_slug)

    @mcp.tool()
    async def studio_create_playbook_draft(title: str, description: str = "") -> str:
        return await mcp_handlers.studio_create_playbook_draft(title, description=description)

    @mcp.tool()
    async def studio_runtime_status(include_debug: bool = False) -> str:
        return await mcp_handlers.studio_runtime_status(include_debug=include_debug)

    stream_builder = getattr(mcp, "streamable_http_app", None)
    if callable(stream_builder):
        inner = stream_builder()
    elif hasattr(mcp, "http_app"):
        inner = mcp.http_app()
    else:
        raise RuntimeError("FastMCP: install mcp>=1.8 with streamable_http_app or http_app")
    tok = (get_settings().studio_mcp_auth_token or "").strip()
    if not tok:
        return inner
    return _wrap_bearer(inner, tok)
