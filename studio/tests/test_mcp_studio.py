from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from pb_studio.core.config import get_settings


def test_mcp_bearer_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    monkeypatch.setenv("STUDIO_MCP_AUTH_TOKEN", "secret-mcp-token")
    get_settings.cache_clear()
    from pb_studio.mcp_server.asgi import build_mcp_asgi_app

    app = build_mcp_asgi_app()
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 401


def test_mcp_bearer_accepts_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    monkeypatch.setenv("STUDIO_MCP_AUTH_TOKEN", "secret-mcp-token")
    get_settings.cache_clear()
    from pb_studio.mcp_server.asgi import build_mcp_asgi_app

    app = build_mcp_asgi_app()
    with TestClient(app) as client:
        r = client.get("/", headers={"Authorization": "Bearer secret-mcp-token"})
        assert r.status_code != 401
