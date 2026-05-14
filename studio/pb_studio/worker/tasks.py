from __future__ import annotations

import asyncio

from pb_studio.celery_app import celery_app
from pb_studio.control_group.system_notification_delivery import run_deliver_pending_standalone
from pb_studio.summaries.generator import run_generate_pending_standalone
from pb_studio.summaries.planner import run_plan_daily_standalone


@celery_app.task(name="pb_studio.worker.ping")
def ping() -> str:
    """Skeleton task for smoke / connectivity checks."""
    return "pong"


@celery_app.task(name="pb_studio.worker.deliver_pending_system_notifications")
def deliver_pending_system_notifications() -> dict[str, int]:
    """Idempotent: re-run safe; processes pending + failed_retryable rows."""
    return asyncio.run(run_deliver_pending_standalone())


@celery_app.task(name="pb_studio.worker.plan_daily_chat_summaries")
def plan_daily_chat_summaries() -> dict[str, int]:
    """Phase 6a: create pending daily summary jobs only (no LLM / generation)."""
    return asyncio.run(run_plan_daily_standalone())


@celery_app.task(name="pb_studio.worker.generate_pending_chat_summaries")
def generate_pending_chat_summaries() -> dict[str, int]:
    """Phase 6b: template summary_text for pending jobs (no Telegram send, no external LLM)."""
    return asyncio.run(run_generate_pending_standalone())
