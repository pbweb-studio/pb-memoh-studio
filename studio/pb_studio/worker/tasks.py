from __future__ import annotations

from pb_studio.celery_app import celery_app


@celery_app.task(name="pb_studio.worker.ping")
def ping() -> str:
    """Skeleton task for smoke / connectivity checks."""
    return "pong"
