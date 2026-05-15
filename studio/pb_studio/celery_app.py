from __future__ import annotations

from datetime import timedelta

from celery import Celery

from pb_studio.core.config import get_settings


def create_celery_app() -> Celery:
    s = get_settings()
    application = Celery(
        "pb_studio",
        broker=s.celery_broker_url,
        backend=s.celery_backend_effective,
    )
    interval_s = max(3, min(int(s.studio_control_commands_interval_seconds or 5), 300))
    nl_interval_s = max(3, min(int(s.studio_nl_process_interval_seconds or 8), 300))
    beat_schedule: dict[str, dict] = {
        "studio-process-control-group-commands": {
            "task": "pb_studio.worker.process_control_group_commands",
            "schedule": timedelta(seconds=interval_s),
        },
    }
    if s.studio_nl_commands_enabled:
        beat_schedule["studio-process-nl-interactions"] = {
            "task": "pb_studio.worker.process_nl_interactions",
            "schedule": timedelta(seconds=nl_interval_s),
        }
    application.conf.update(
        task_default_queue="studio",
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        beat_schedule=beat_schedule,
    )
    application.autodiscover_tasks(["pb_studio.worker"])
    return application


celery_app = create_celery_app()
