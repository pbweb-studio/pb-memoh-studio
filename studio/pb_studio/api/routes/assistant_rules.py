from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from pb_studio.api.deps import DbSession, verify_admin_optional
from pb_studio.assistant_rules.schemas import (
    AssistantRuleAuditOut,
    AssistantRuleCreate,
    AssistantRuleDisableBody,
    AssistantRuleOut,
    AssistantRulePatch,
)
from pb_studio.assistant_rules import service as rules_service

router = APIRouter(
    prefix="/assistant-rules",
    tags=["assistant-rules"],
    dependencies=[Depends(verify_admin_optional)],
)


@router.get("/audit", response_model=list[AssistantRuleAuditOut])
async def get_assistant_rules_audit(
    session: DbSession,
    rule_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AssistantRuleAuditOut]:
    rows = await rules_service.list_audit(session, rule_id=rule_id, limit=limit)
    return [AssistantRuleAuditOut.model_validate(r) for r in rows]


@router.get("", response_model=list[AssistantRuleOut])
async def get_assistant_rules(
    session: DbSession,
    scope: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AssistantRuleOut]:
    rows = await rules_service.list_rules(session, scope=scope, status=status_filter, limit=limit)
    return [AssistantRuleOut.model_validate(r) for r in rows]


@router.post("", response_model=AssistantRuleOut, status_code=status.HTTP_201_CREATED)
async def post_assistant_rule(session: DbSession, body: AssistantRuleCreate) -> AssistantRuleOut:
    try:
        row = await rules_service.create_rule(
            session,
            scope=body.scope,
            rule_text=body.rule_text,
            project_id=body.project_id,
            chat_id=body.chat_id,
            source=body.source,
            metadata_json=body.metadata_json,
        )
        return AssistantRuleOut.model_validate(row)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{rule_id}", response_model=AssistantRuleOut)
async def get_assistant_rule(session: DbSession, rule_id: UUID) -> AssistantRuleOut:
    row = await rules_service.get_rule(session, rule_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="rule not found")
    return AssistantRuleOut.model_validate(row)


@router.patch("/{rule_id}", response_model=AssistantRuleOut)
async def patch_assistant_rule(session: DbSession, rule_id: UUID, body: AssistantRulePatch) -> AssistantRuleOut:
    try:
        row = await rules_service.patch_rule(
            session,
            rule_id,
            rule_text=body.rule_text,
            metadata_json=body.metadata_json,
            actor_telegram_user_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="rule not found")
    return AssistantRuleOut.model_validate(row)


@router.post("/{rule_id}/disable", response_model=AssistantRuleOut)
async def post_assistant_rule_disable(
    session: DbSession,
    rule_id: UUID,
    body: AssistantRuleDisableBody | None = Body(default=None),
) -> AssistantRuleOut:
    reason = body.reason if body else None
    row = await rules_service.disable_rule(session, rule_id, reason=reason, actor_telegram_user_id=None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="rule not found")
    return AssistantRuleOut.model_validate(row)
