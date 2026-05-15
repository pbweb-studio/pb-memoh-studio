from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.assistant_rules.constants import AssistantRuleScope, AssistantRuleSource
from pb_studio.assistant_rules import service as assistant_rules_service
from pb_studio.control_commands.service import _send_text_to_control_group
from pb_studio.control_group.telegram_outbound import redact_secrets
from pb_studio.core.config import Settings, get_settings
from pb_studio.core.database import dispose_engine, get_session_factory
from pb_studio.nl.constants import LearningType, NlInteractionStatus
from pb_studio.nl.executor import format_nl_reply, learning_confirmation_message
from pb_studio.nl.models import StudioMemoryItem, StudioNlInteraction, StudioPlaybook
from pb_studio.nl.router import route_nl
from pb_studio.nl.scan import scan_mirror_for_nl_aliases
from pb_studio.nl.schemas import IntentEnum, NLRouterDecision, RouterModeEnum

logger = logging.getLogger(__name__)

CONFIRM_TTL = timedelta(minutes=30)
_YES = frozenset({"да", "yes", "ага", "ок", "y"})
_NO = frozenset({"нет", "no", "n"})


def _looks_like_independent_nl_question(text: str) -> bool:
    """Не считать сообщение ответом на pending learning (Studio без reply_to из Memoh)."""
    s = (text or "").strip()
    if not s:
        return False
    low = s.lower()
    if "?" in s and len(s) > 18:
        return True
    needles = (
        "на какой модели",
        "какая модель",
        "отчёт за",
        "отчет за",
        "дай отчёт",
        "дай отчет",
        "дай сводк",
        "сводк за",
        "какие чаты",
        "список чат",
        "группы ты видишь",
        "что горит",
        "кто без ответа",
        "просроч",
        "инцидент",
        "базе знан",
        "найди в базе",
        "что нового",
        "какой llm",
    )
    return any(n in low for n in needles)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _find_pending_confirmation(
    session: AsyncSession,
    *,
    control_group_chat_id: Any,
    sender_id: int | None,
) -> StudioNlInteraction | None:
    if sender_id is None:
        return None
    since = utcnow() - CONFIRM_TTL
    stmt = (
        select(StudioNlInteraction)
        .where(
            and_(
                StudioNlInteraction.control_group_chat_id == control_group_chat_id,
                StudioNlInteraction.sender_telegram_user_id == sender_id,
                StudioNlInteraction.status == NlInteractionStatus.PENDING_CONFIRMATION,
                StudioNlInteraction.created_at >= since,
            )
        )
        .order_by(StudioNlInteraction.created_at.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def _try_handle_confirmation_reply(
    session: AsyncSession,
    settings: Settings,
    row: StudioNlInteraction,
    *,
    send_message: Any = None,
) -> bool:
    """If row is short yes/no/project line for pending learning, apply and return True."""
    pending = await _find_pending_confirmation(
        session, control_group_chat_id=row.control_group_chat_id, sender_id=row.sender_telegram_user_id
    )
    if pending is None:
        return False
    if _looks_like_independent_nl_question(row.input_text):
        return False
    raw = (row.input_text or "").strip().lower()
    if len(raw) > 120:
        return False

    async def reply(txt: str) -> int | None:
        ok, _hs, mid = await _send_text_to_control_group(session, settings, txt, send_message=send_message)
        return mid if ok else None

    draft = (pending.decision_json or {}).get("pending_learning") or {}
    lt = str(draft.get("learning_type") or "")

    if raw in _NO:
        row.status = NlInteractionStatus.IGNORED
        row.processed_at = utcnow()
        pending.status = NlInteractionStatus.IGNORED
        pending.processed_at = utcnow()
        await reply("Отменено, правило не сохранено.")
        return True

    if raw in _YES and lt == LearningType.BEHAVIOR_RULE:
        text = str(draft.get("suggested_rule_text") or "").strip()
        if not text:
            await reply("Черновик правила пуст.")
        else:
            await assistant_rules_service.create_rule(
                session,
                scope=AssistantRuleScope.GLOBAL,
                rule_text=text,
                source=AssistantRuleSource.CONTROL_GROUP,
                created_by_telegram_user_id=row.sender_telegram_user_id,
                created_from_message_id=row.source_message_id,
            )
            await reply("Готово, правило сохранено (глобально).")
        row.status = NlInteractionStatus.PROCESSED
        row.processed_at = utcnow()
        pending.status = NlInteractionStatus.PROCESSED
        pending.processed_at = utcnow()
        return True

    if raw in _YES and lt == LearningType.WORKFLOW_PLAYBOOK:
        pb = StudioPlaybook(
            title=str(draft.get("draft_title") or "Playbook"),
            description=str(draft.get("draft_description") or "")[:8000],
            scope_type="global",
            scope_id=None,
            trigger_examples_json=[],
            steps_json=[],
            status="draft",
            created_by_telegram_user_id=row.sender_telegram_user_id,
            source_message_id=row.source_message_id,
            metadata_json={"source": "nl_learning"},
        )
        session.add(pb)
        await reply("Черновик playbook сохранён (draft).")
        row.status = NlInteractionStatus.PROCESSED
        row.processed_at = utcnow()
        pending.status = NlInteractionStatus.PROCESSED
        pending.processed_at = utcnow()
        return True

    if raw in _YES and lt == LearningType.KNOWLEDGE_NOTE:
        note = str(draft.get("note_text") or "").strip()
        if not note:
            await reply("Заметка пуста.")
        else:
            session.add(
                StudioMemoryItem(
                    scope_type="global",
                    scope_id=None,
                    item_type="fact",
                    text=note[:8000],
                    source_message_id=row.source_message_id,
                    source_update_id=row.source_update_id,
                    created_by_telegram_user_id=row.sender_telegram_user_id,
                    status="active",
                    confidence=None,
                    metadata_json={"source": "nl_learning"},
                )
            )
            await reply("Заметка сохранена.")
        row.status = NlInteractionStatus.PROCESSED
        row.processed_at = utcnow()
        pending.status = NlInteractionStatus.PROCESSED
        pending.processed_at = utcnow()
        return True

    if raw in _YES and lt == LearningType.KNOWLEDGE_DOCUMENT:
        body = str(draft.get("body") or "").strip()
        if not body:
            await reply("Текст документа пуст.")
        else:
            from pb_studio.knowledge import service as knowledge_service
            from pb_studio.knowledge.constants import KnowledgeDocumentStatus

            title = (str(draft.get("title") or "Документ из NL").strip() or "Документ из NL")[:512]
            doc = await knowledge_service.create_document(
                session,
                title=title,
                source_type="nl_learning",
                metadata_json={"source": "nl_learning"},
                status=KnowledgeDocumentStatus.DRAFT,
            )
            await knowledge_service.create_document_version_from_text(
                session, doc.id, body, settings, metadata_json={"source": "nl_learning"}
            )
            await reply(f"Документ KB создан (черновик), id={str(doc.id)[:8]}…")
        row.status = NlInteractionStatus.PROCESSED
        row.processed_at = utcnow()
        pending.status = NlInteractionStatus.PROCESSED
        pending.processed_at = utcnow()
        return True

    m = re.match(r"^для\s+проекта\s+(\S+)", raw)
    if m and lt == LearningType.BEHAVIOR_RULE:
        slug_try = m.group(1).strip()
        from pb_studio.projects.service import get_project_by_slug

        try:
            proj = await get_project_by_slug(session, slug_try)
        except ValueError:
            proj = None
        if proj is None:
            await reply("Проект не найден по slug, попробуйте ещё раз.")
            return True
        text = str(draft.get("suggested_rule_text") or "").strip()
        if text:
            await assistant_rules_service.create_rule(
                session,
                scope=AssistantRuleScope.PROJECT,
                rule_text=text,
                project_id=proj.id,
                source=AssistantRuleSource.CONTROL_GROUP,
                created_by_telegram_user_id=row.sender_telegram_user_id,
                created_from_message_id=row.source_message_id,
            )
            await reply(f"Правило сохранено для проекта {proj.slug}.")
        row.status = NlInteractionStatus.PROCESSED
        row.processed_at = utcnow()
        pending.status = NlInteractionStatus.PROCESSED
        pending.processed_at = utcnow()
        return True

    if "для этого чата" in raw and lt == LearningType.BEHAVIOR_RULE:
        from pb_studio.control_group.service import get_control_group_chat

        cg = await get_control_group_chat(session)
        if cg is None:
            await reply("Control group не найдена.")
            return True
        text = str(draft.get("suggested_rule_text") or "").strip()
        if text:
            await assistant_rules_service.create_rule(
                session,
                scope=AssistantRuleScope.CHAT,
                rule_text=text,
                chat_id=cg.id,
                source=AssistantRuleSource.CONTROL_GROUP,
                created_by_telegram_user_id=row.sender_telegram_user_id,
                created_from_message_id=row.source_message_id,
            )
            await reply("Правило сохранено для этого чата (control group).")
        row.status = NlInteractionStatus.PROCESSED
        row.processed_at = utcnow()
        pending.status = NlInteractionStatus.PROCESSED
        pending.processed_at = utcnow()
        return True

    return False


async def _process_one_nl(
    session: AsyncSession,
    row: StudioNlInteraction,
    settings: Settings,
    *,
    send_message: Any = None,
) -> None:
    now = utcnow()
    if not settings.studio_nl_commands_enabled:
        row.status = NlInteractionStatus.IGNORED
        row.processed_at = now
        return

    if await _try_handle_confirmation_reply(session, settings, row, send_message=send_message):
        return

    allowed = settings.studio_control_commands_allowed_user_ids_set
    if allowed and row.sender_telegram_user_id not in allowed:
        ok, _hs, mid = await _send_text_to_control_group(
            session, settings, "Нет прав на NL-команды в этой группе.", send_message=send_message
        )
        row.status = NlInteractionStatus.FAILED
        row.last_error = "access_denied"
        row.processed_at = now
        row.response_telegram_message_id = mid
        return

    try:
        decision = await route_nl(settings, row.input_text)
    except Exception as exc:  # noqa: BLE001
        tok = (settings.telegram_bot_token or "").strip()
        row.status = NlInteractionStatus.FAILED
        row.last_error = redact_secrets(str(exc)[:500], tok or None)
        row.processed_at = now
        return

    row.intent = decision.intent.value if decision.intent else None
    row.confidence = decision.confidence
    row.mode = decision.mode.value
    row.decision_json = decision.model_dump(mode="json")

    ex = float(settings.studio_nl_router_confidence_execute)
    cl = float(settings.studio_nl_router_confidence_clarify)

    if decision.confidence < cl:
        decision = NLRouterDecision(
            mode=RouterModeEnum.clarify,
            intent=IntentEnum.unclear,
            confidence=0.5,
            parameters={},
            clarify_question=decision.clarify_question or "Уточните запрос.",
        )

    if decision.mode == RouterModeEnum.learning:
        draft = dict(decision.parameters or {})
        draft["learning_type"] = draft.get("learning_type") or LearningType.BEHAVIOR_RULE
        row.status = NlInteractionStatus.PENDING_CONFIRMATION
        row.decision_json = {**row.decision_json, "pending_learning": draft}
        msg = learning_confirmation_message(draft)
        ok, _hs, mid = await _send_text_to_control_group(session, settings, msg, send_message=send_message)
        row.response_telegram_message_id = mid
        row.reply_text = msg
        row.processed_at = now
        return

    if decision.mode == RouterModeEnum.business_action and decision.confidence < ex:
        txt = decision.clarify_question or "Низкая уверенность: уточните формулировку."
        ok, _hs, mid = await _send_text_to_control_group(session, settings, txt, send_message=send_message)
        row.response_telegram_message_id = mid
        row.reply_text = txt
        row.status = NlInteractionStatus.PROCESSED
        row.processed_at = now
        return

    try:
        out = await format_nl_reply(session, settings, decision, raw_input=row.input_text)
    except Exception as exc:  # noqa: BLE001
        tok = (settings.telegram_bot_token or "").strip()
        row.status = NlInteractionStatus.FAILED
        row.last_error = redact_secrets(str(exc)[:500], tok or None)
        row.processed_at = now
        return

    ok, _hs, mid = await _send_text_to_control_group(session, settings, out, send_message=send_message)
    row.response_telegram_message_id = mid
    row.reply_text = out
    row.status = NlInteractionStatus.PROCESSED
    row.processed_at = now


async def run_nl_interactions_standalone(
    *,
    settings: Settings | None = None,
    batch_limit: int | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    factory = get_session_factory(settings)
    counts: dict[str, Any] = {"scanned_aliases": 0, "inserted_aliases": 0, "processed_nl": 0}
    try:
        async with factory() as session:
            scan_counts = await scan_mirror_for_nl_aliases(
                session, settings, batch_limit=batch_limit or settings.studio_control_commands_max_batch
            )
            counts["scanned_aliases"] = scan_counts.get("scanned", 0)
            counts["inserted_aliases"] = scan_counts.get("inserted", 0)
            await session.commit()

        async with factory() as session:
            lim = min(max(batch_limit or settings.studio_control_commands_max_batch, 1), 200)
            stmt = (
                select(StudioNlInteraction)
                .where(StudioNlInteraction.status == NlInteractionStatus.PENDING)
                .order_by(StudioNlInteraction.created_at.asc())
                .limit(lim)
            )
            rows = list((await session.scalars(stmt)).all())
            for row in rows:
                await _process_one_nl(session, row, settings)
                counts["processed_nl"] += 1
            await session.commit()
    finally:
        await dispose_engine()
    return counts
