from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from pb_studio.core.config import get_settings
from pb_studio.core.database import dispose_engine
from pb_studio.core.redis_client import close_redis


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await dispose_engine()
    await close_redis()


def create_app() -> FastAPI:
    application = FastAPI(
        title="pb-studio-api",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        s = get_settings()
        return {"status": "ok", "service": "studio-api", "env": s.studio_env}

    return application


app = create_app()
