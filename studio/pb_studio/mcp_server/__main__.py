from __future__ import annotations

import uvicorn

from pb_studio.core.config import get_settings
from pb_studio.mcp_server.asgi import build_mcp_asgi_app


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        build_mcp_asgi_app(),
        host=settings.studio_mcp_listen_host,
        port=int(settings.studio_mcp_listen_port),
        factory=False,
        log_level="info",
        # Docker DNS (e.g. Host: studio-mcp:8765) must be accepted for Memoh federation probes.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
