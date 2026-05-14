from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.assistant_rules.constants import (
    AssistantRuleAuditAction,
    AssistantRuleScope,
    AssistantRuleSource,
    AssistantRuleStatus,
)
from pb_studio.assistant_rules.models import StudioAssistantRule, StudioAssistantRuleAudit
from pb_studio.event_mirror.models import StudioChat
from pb_studio.projects.models import StudioProject


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_scope_payload(
    scope: str,
    *,
    project_id: UUID | None,
    chat_id: UUID | None,
) -> None:
    if scope == AssistantRuleScope.GLOBAL:
        if project_id is not None or chat_id is not None:
            raise ValueError("global scope requires null project_id and chat_id")
    elif scope == AssistantRuleScope.PROJECT:
        if project_id is None or chat_id is not None:
            raise ValueError("project scope requires project_id and null chat_id")
    elif scope == AssistantRuleScope.CHAT:
        if chat_id is None or project_id is not None:
            raise ValueError("chat scope requires chat_id and null project_id")
    else:
        raise ValueError("invalid scope")


async def _append_audit(
    session: AsyncSession,
    *,
    rule_id: UUID | None,
    action: str,
    actor_telegram_user_id: int | None,
    payload: dict[str, Any] | None,
) -> None:
    row = StudioAssistantRuleAudit(
        rule_id=rule_id,
        action=action,
        actor_telegram_user_id=actor_telegram_user_id,
        payload_json=payload,
    )
    session.add(row)
    await session.flush()


async def create_rule(
    session: AsyncSession,
    *,
    scope: str,
    rule_text: str,
    project_id: UUID | None = None,
    chat_id: UUID | None = None,
    source: str = AssistantRuleSource.MANUAL,
    created_by_telegram_user_id: int | None = None,
    created_from_message_id: int | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> StudioAssistantRule:
    scope = scope.strip().lower()
    _validate_scope_payload(scope, project_id=project_id, chat_id=chat_id)
    if scope == AssistantRuleScope.PROJECT:
        proj = await session.get(StudioProject, project_id)
        if proj is None:
            raise ValueError("project not found")
    if scope == AssistantRuleScope.CHAT:
        ch = await session.get(StudioChat, chat_id)
        if ch is None:
            raise ValueError("chat not found")
    text = rule_text.strip()
    if not text:
        raise ValueError("empty rule_text")
    src = source.strip().lower() or AssistantRuleSource.MANUAL
    if src not in (AssistantRuleSource.MANUAL, AssistantRuleSource.CONTROL_GROUP):
        raise ValueError("invalid source")

    row = StudioAssistantRule(
        scope=scope,
        project_id=project_id,
        chat_id=chat_id,
        rule_text=text,
        status=AssistantRuleStatus.ACTIVE,
        source=src,
        created_by_telegram_user_id=created_by_telegram_user_id,
        created_from_message_id=created_from_message_id,
        metadata_json=metadata_json,
    )
    session.add(row)
    await session.flush()
    await _append_audit(
        session,
        rule_id=row.id,
        action=AssistantRuleAuditAction.CREATED,
        actor_telegram_user_id=created_by_telegram_user_id,
        payload={
            "scope": scope,
            "source": src,
            "rule_text_len": len(text),
            "project_id": str(project_id) if project_id else None,
            "chat_id": str(chat_id) if chat_id else None,
        },
    )
    return row


async def list_rules(
    session: AsyncSession,
    *,
    scope: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[StudioAssistantRule]:
    lim = min(max(limit, 1), 500)
    q = select(StudioAssistantRule).order_by(StudioAssistantRule.created_at.desc()).limit(lim)
    if scope:
        q = q.where(StudioAssistantRule.scope == scope.strip().lower())
    if status:
        q = q.where(StudioAssistantRule.status == status.strip().lower())
    return list((await session.scalars(q)).all())


async def get_rule(session: AsyncSession, rule_id: UUID) -> StudioAssistantRule | None:
    return await session.get(StudioAssistantRule, rule_id)


async def patch_rule(
    session: AsyncSession,
    rule_id: UUID,
    *,
    rule_text: str | None,
    metadata_json: dict[str, Any] | None,
    actor_telegram_user_id: int | None = None,
) -> StudioAssistantRule | None:
    row = await session.get(StudioAssistantRule, rule_id)
    if row is None:
        return None
    if row.status != AssistantRuleStatus.ACTIVE:
        raise ValueError("rule is not active")
    changed = False
    if rule_text is not None:
        t = rule_text.strip()
        if not t:
            raise ValueError("empty rule_text")
        row.rule_text = t
        changed = True
    if metadata_json is not None:
        row.metadata_json = metadata_json
        changed = True
    if not changed:
        return row
    row.updated_at = utcnow()
    await session.flush()
    await _append_audit(
        session,
        rule_id=row.id,
        action=AssistantRuleAuditAction.UPDATED,
        actor_telegram_user_id=actor_telegram_user_id,
        payload={"rule_text_len": len(row.rule_text)},
    )
    return row


async def disable_rule(
    session: AsyncSession,
    rule_id: UUID,
    *,
    reason: str | None = None,
    actor_telegram_user_id: int | None = None,
) -> StudioAssistantRule | None:
    row = await session.get(StudioAssistantRule, rule_id)
    if row is None:
        return None
    if row.status == AssistantRuleStatus.DISABLED:
        return row
    row.status = AssistantRuleStatus.DISABLED
    row.disabled_at = utcnow()
    row.disable_reason = (reason or "").strip() or None
    row.updated_at = utcnow()
    await session.flush()
    await _append_audit(
        session,
        rule_id=row.id,
        action=AssistantRuleAuditAction.DISABLED,
        actor_telegram_user_id=actor_telegram_user_id,
        payload={"disable_reason_len": len(row.disable_reason or "")},
    )
    return row


_SCOPE_ORDER = {
    AssistantRuleScope.GLOBAL: 0,
    AssistantRuleScope.PROJECT: 1,
    AssistantRuleScope.CHAT: 2,
}


async def list_active_rules_for_kb_rag(
    session: AsyncSession,
    *,
    project_id: UUID | None,
    chat_id: UUID | None,
) -> list[StudioAssistantRule]:
    """
    Активные правила для KB RAG: global; + project при заданном project_id;
    + chat при заданном chat_id. Без Memoh — только выборка для Studio RAG.
    """
    clauses = [
        and_(
            StudioAssistantRule.status == AssistantRuleStatus.ACTIVE,
            StudioAssistantRule.scope == AssistantRuleScope.GLOBAL,
        )
    ]
    if project_id is not None:
        clauses.append(
            and_(
                StudioAssistantRule.status == AssistantRuleStatus.ACTIVE,
                StudioAssistantRule.scope == AssistantRuleScope.PROJECT,
                StudioAssistantRule.project_id == project_id,
            )
        )
    if chat_id is not None:
        clauses.append(
            and_(
                StudioAssistantRule.status == AssistantRuleStatus.ACTIVE,
                StudioAssistantRule.scope == AssistantRuleScope.CHAT,
                StudioAssistantRule.chat_id == chat_id,
            )
        )
    q = select(StudioAssistantRule).where(or_(*clauses))
    rows = list((await session.scalars(q)).all())
    rows.sort(key=lambda r: (_SCOPE_ORDER.get(r.scope, 99), r.created_at))
    return rows


async def list_audit(
    session: AsyncSession,
    *,
    rule_id: UUID | None = None,
    limit: int = 100,
) -> list[StudioAssistantRuleAudit]:
    lim = min(max(limit, 1), 500)
    q = select(StudioAssistantRuleAudit).order_by(StudioAssistantRuleAudit.created_at.desc()).limit(lim)
    if rule_id is not None:
        q = q.where(StudioAssistantRuleAudit.rule_id == rule_id)
    return list((await session.scalars(q)).all())
