from __future__ import annotations

from celery import Celery

from pb_studio.core.config import get_settings


def create_celery_app() -> Celery:
    s = get_settings()
    application = Celery(
        "pb_studio",
        broker=s.celery_broker_url,
        backend=s.celery_backend_effective,
    )
    application.conf.update(
        task_default_queue="studio",
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )
    application.autodiscover_tasks(["pb_studio.worker"])
    return application


celery_app = create_celery_app()
