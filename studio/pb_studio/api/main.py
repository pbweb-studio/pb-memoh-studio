from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from pb_studio.api.routes import control as control_routes
from pb_studio.api.routes import control_commands as control_commands_routes
from pb_studio.api.routes import events as events_routes
from pb_studio.api.routes import notifications as notifications_routes
from pb_studio.api.routes import project_digests as project_digests_routes
from pb_studio.api.routes import projects as projects_routes
from pb_studio.api.routes import sla as sla_routes
from pb_studio.api.routes import summaries as summaries_routes
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

    application.include_router(events_routes.router)
    application.include_router(control_routes.router)
    application.include_router(control_commands_routes.router)
    application.include_router(notifications_routes.router)
    application.include_router(summaries_routes.router)
    application.include_router(sla_routes.router)
    application.include_router(projects_routes.router)
    application.include_router(project_digests_routes.router)

    return application


app = create_app()
