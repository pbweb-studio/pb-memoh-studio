from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pb_studio.core.config import get_settings
from pb_studio.mcp_tools import extra_handlers as mcp_extra_handlers
from pb_studio.mcp_tools import handlers as mcp_handlers


def _normalize_streamable_host(
    app: Callable[..., Awaitable[None]],
    listen_port: int,
) -> Callable[..., Awaitable[None]]:
    """MCP streamable stack rejects Host: <docker-service>:port; normalize to loopback."""

    async def middleware(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await app(scope, receive, send)
            return
        raw_headers = list(scope.get("headers") or [])
        new_headers: list[tuple[bytes, bytes]] = []
        loop = f"127.0.0.1:{listen_port}".encode("ascii")
        for key, val in raw_headers:
            if key.lower() == b"host":
                try:
                    hostport = val.decode("latin-1")
                except Exception:
                    new_headers.append((key, val))
                    continue
                hostname = hostport.split(":", 1)[0].strip().lower()
                if hostname not in ("127.0.0.1", "localhost", "::1"):
                    new_headers.append((b"host", loop))
                else:
                    new_headers.append((key, val))
            else:
                new_headers.append((key, val))
        if not any(k.lower() == b"host" for k, _ in new_headers):
            new_headers.append((b"host", loop))
        new_scope = dict(scope)
        new_scope["headers"] = new_headers
        await app(new_scope, receive, send)

    return middleware


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

    # ===== MVP v1: role-aware context, smart reports, projects, rules =====

    @mcp.tool()
    async def studio_get_chat_context(
        telegram_chat_id: int,
        from_user_id: int | None = None,
    ) -> str:
        """Контекст чата для Memoh: role, project, active_rules, can_respond_to_user.

        ОБЯЗАТЕЛЬНО вызывать перед ответом в любом групповом чате, кроме
        управляющей группы и личных DM.
        """
        return await mcp_extra_handlers.studio_get_chat_context(
            telegram_chat_id=telegram_chat_id, from_user_id=from_user_id
        )

    @mcp.tool()
    async def studio_smart_chat_report(
        chat_id_or_name: str,
        period: str = "today",
        max_messages: int = 200,
    ) -> str:
        """LLM-отчёт «по смыслу» чата за период (today | yesterday | week).
        Формат отчёта выбирает LLM из содержимого (задачи / лиды / согласования / обзор).
        """
        return await mcp_extra_handlers.studio_smart_chat_report(
            chat_id_or_name=chat_id_or_name, period=period, max_messages=max_messages
        )

    @mcp.tool()
    async def studio_assign_chat_role(telegram_chat_id: int, role: str) -> str:
        """Назначить чату роль: client_chat | project_chat | internal_chat | service_chat | unknown."""
        return await mcp_extra_handlers.studio_assign_chat_role(
            telegram_chat_id=telegram_chat_id, role=role
        )

    @mcp.tool()
    async def studio_set_control_group(telegram_chat_id: int) -> str:
        """Назначить чат управляющей группой (control_group)."""
        return await mcp_extra_handlers.studio_set_control_group(
            telegram_chat_id=telegram_chat_id
        )

    @mcp.tool()
    async def studio_get_active_rules(scope: str = "global", scope_id: str | None = None) -> str:
        """Активные правила ассистента (scope: global | project | chat).
        Для project/chat укажи scope_id: slug проекта или telegram_chat_id/UUID."""
        return await mcp_extra_handlers.studio_get_active_rules(
            scope=scope, scope_id=scope_id
        )

    @mcp.tool()
    async def studio_create_project(name: str, slug: str | None = None) -> str:
        """Создать проект. Если slug не задан — сгенерируется из name."""
        return await mcp_extra_handlers.studio_create_project(name=name, slug=slug)

    @mcp.tool()
    async def studio_bind_chat_to_project(
        telegram_chat_id: int,
        project_slug: str,
        role_in_project: str = "secondary",
    ) -> str:
        """Привязать чат к проекту. Роль в проекте: primary | secondary | client_facing | …"""
        return await mcp_extra_handlers.studio_bind_chat_to_project(
            telegram_chat_id=telegram_chat_id,
            project_slug=project_slug,
            role_in_project=role_in_project,
        )

    @mcp.tool()
    async def studio_disable_rule(rule_id: str, reason: str | None = None) -> str:
        """Отключить правило ассистента по UUID."""
        return await mcp_extra_handlers.studio_disable_rule(rule_id=rule_id, reason=reason)

    @mcp.tool()
    async def studio_get_recent_messages(chat_id_or_name: str, limit: int = 30) -> str:
        """Последние N сообщений чата (для контекста, без LLM-обработки)."""
        return await mcp_extra_handlers.studio_get_recent_messages(
            chat_id_or_name=chat_id_or_name, limit=limit
        )

    stream_builder = getattr(mcp, "streamable_http_app", None)
    if callable(stream_builder):
        inner = stream_builder()
    elif hasattr(mcp, "http_app"):
        inner = mcp.http_app()
    else:
        raise RuntimeError("FastMCP: install mcp>=1.8 with streamable_http_app or http_app")
    settings = get_settings()
    listen_port = int(settings.studio_mcp_listen_port)
    inner = _normalize_streamable_host(inner, listen_port)
    tok = (settings.studio_mcp_auth_token or "").strip()
    if not tok:
        return inner
    return _wrap_bearer(inner, tok)
