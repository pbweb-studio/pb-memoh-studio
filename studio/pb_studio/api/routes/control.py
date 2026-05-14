from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from pb_studio.api.deps import DbSession, verify_admin_optional
from pb_studio.control_group.schemas import ControlGroupOut, SetChatRoleRequest, SetControlGroupRequest, StudioChatOut
from pb_studio.control_group.service import (
    get_control_group_chat,
    list_chats,
    set_chat_role,
    set_control_group_by_telegram_id,
)

router = APIRouter(tags=["control-group"])


@router.get("/control-group", response_model=ControlGroupOut, dependencies=[Depends(verify_admin_optional)])
async def get_control_group(session: DbSession) -> ControlGroupOut:
    chat = await get_control_group_chat(session)
    if chat is None:
        return ControlGroupOut(active=False, studio_chat=None)
    return ControlGroupOut(active=True, studio_chat=StudioChatOut.model_validate(chat))


@router.post("/control-group/set", dependencies=[Depends(verify_admin_optional)])
async def post_control_group_set(session: DbSession, body: SetControlGroupRequest) -> ControlGroupOut:
    try:
        await set_control_group_by_telegram_id(session, body.telegram_chat_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    chat = await get_control_group_chat(session)
    assert chat is not None
    return ControlGroupOut(active=True, studio_chat=StudioChatOut.model_validate(chat))


@router.post("/chats/{chat_id}/role", dependencies=[Depends(verify_admin_optional)])
async def post_chat_role(session: DbSession, chat_id: UUID, body: SetChatRoleRequest) -> StudioChatOut:
    try:
        chat = await set_chat_role(session, studio_chat_id=chat_id, role=body.role)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return StudioChatOut.model_validate(chat)


@router.get("/chats", response_model=list[StudioChatOut], dependencies=[Depends(verify_admin_optional)])
async def get_chats(session: DbSession) -> list[StudioChatOut]:
    rows = await list_chats(session, unassigned_only=False)
    return [StudioChatOut.model_validate(r) for r in rows]


@router.get("/chats/unassigned", response_model=list[StudioChatOut], dependencies=[Depends(verify_admin_optional)])
async def get_chats_unassigned(session: DbSession) -> list[StudioChatOut]:
    rows = await list_chats(session, unassigned_only=True)
    return [StudioChatOut.model_validate(r) for r in rows]
