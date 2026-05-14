from __future__ import annotations

import asyncio

from pb_studio.celery_app import celery_app
from pb_studio.control_group.system_notification_delivery import run_deliver_pending_standalone


@celery_app.task(name="pb_studio.worker.ping")
def ping() -> str:
    """Skeleton task for smoke / connectivity checks."""
    return "pong"


@celery_app.task(name="pb_studio.worker.deliver_pending_system_notifications")
def deliver_pending_system_notifications() -> dict[str, int]:
    """Idempotent: re-run safe; processes pending + failed_retryable rows."""
    return asyncio.run(run_deliver_pending_standalone())
