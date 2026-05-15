from __future__ import annotations

import asyncio
from typing import Any

from pb_studio.celery_app import celery_app
from pb_studio.control_commands.service import run_control_commands_standalone
from pb_studio.control_group.system_notification_delivery import run_deliver_pending_standalone
from pb_studio.summaries.generator import run_generate_pending_standalone
from pb_studio.summaries.planner import run_plan_daily_standalone
from pb_studio.knowledge.service import run_embed_pending_knowledge_standalone, run_parse_pending_knowledge_standalone
from pb_studio.project_digests.service import (
    run_deliver_pending_project_digests_standalone,
    run_generate_daily_project_digests_standalone,
)
from pb_studio.sla.detector import run_sla_detection_standalone
from pb_studio.summaries.summary_delivery import run_deliver_summaries_standalone
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


@celery_app.task(name="pb_studio.worker.deliver_pending_chat_summaries")
def deliver_pending_chat_summaries() -> dict[str, int]:
    """Phase 6d: deliver generated summaries to Telegram control group (sendMessage only)."""
    return asyncio.run(run_deliver_summaries_standalone())


@celery_app.task(name="pb_studio.worker.process_control_group_summary_commands")
def process_control_group_summary_commands() -> dict[str, Any]:
    """Phase 7a: Event Mirror → команды /summary_* в control group; идемпотентно по уникальным ключам."""
    return asyncio.run(run_control_commands_standalone())


@celery_app.task(name="pb_studio.worker.process_control_group_commands")
def process_control_group_commands() -> dict[str, Any]:
    """Phase 9a: те же /summary_* плюс /project_* из control group (Event Mirror + pending commands)."""
    return asyncio.run(run_control_commands_standalone())


@celery_app.task(name="pb_studio.worker.detect_sla_incidents")
def detect_sla_incidents() -> dict[str, int]:
    """Phase 8a: SLA по studio_messages (client/project), без LLM; уведомления только в control group."""
    return asyncio.run(run_sla_detection_standalone())


@celery_app.task(name="pb_studio.worker.generate_daily_project_digests")
def generate_daily_project_digests() -> dict[str, int]:
    """Phase 9b: дайджесты проектов за вчера (UTC) из chat summaries; без LLM."""
    return asyncio.run(run_generate_daily_project_digests_standalone())


@celery_app.task(name="pb_studio.worker.deliver_pending_project_digests")
def deliver_pending_project_digests() -> dict[str, int]:
    """Phase 9b: доставка project digest в control group (sendMessage)."""
    return asyncio.run(run_deliver_pending_project_digests_standalone())


@celery_app.task(name="pb_studio.worker.parse_pending_knowledge_documents")
def parse_pending_knowledge_documents() -> dict[str, int]:
    """Phase 10b: parse pending KB document versions (plain text / markdown; no embeddings)."""
    return asyncio.run(run_parse_pending_knowledge_standalone())


@celery_app.task(name="pb_studio.worker.embed_pending_knowledge_chunks")
def embed_pending_knowledge_chunks() -> dict[str, int]:
    """Phase 10c: embed pending KB chunks (deterministic provider; pgvector search on Postgres)."""
    return asyncio.run(run_embed_pending_knowledge_standalone())


