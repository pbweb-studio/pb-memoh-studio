from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    studio_env: str = Field(default="local", description="STUDIO_ENV")
    database_url: str = Field(
        default="postgresql+asyncpg://pb_studio:pb_studio_dev@127.0.0.1:5433/pb_studio",
        description="DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://127.0.0.1:6380/0",
        description="REDIS_URL",
    )
    celery_broker_url: str = Field(
        default="redis://127.0.0.1:6380/1",
        description="CELERY_BROKER_URL",
    )
    celery_result_backend: str | None = Field(
        default=None,
        description="CELERY_RESULT_BACKEND; если пусто — используется broker",
    )

    api_host: str = Field(default="0.0.0.0", description="STUDIO_API_HOST")
    api_port: int = Field(default=8000, description="STUDIO_API_PORT")

    studio_events_ingest_token: str | None = Field(
        default=None,
        description="STUDIO_EVENTS_INGEST_TOKEN — если задан, POST /events/telegram требует Authorization: Bearer …",
    )
    studio_mirror_enqueue_user_messages: bool = Field(
        default=False,
        description="STUDIO_MIRROR_ENQUEUE_USER_MESSAGES — enqueue в Response Queue только для user text/caption",
    )

    @property
    def celery_backend_effective(self) -> str:
        return self.celery_result_backend or self.celery_broker_url

    @property
    def database_url_sync_for_alembic(self) -> str:
        u = self.database_url
        if "+asyncpg" in u:
            return u.replace("+asyncpg", "+psycopg2", 1)
        return u


@lru_cache
def get_settings() -> Settings:
    return Settings()
