from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pb_studio.api.deps import DbSession, SettingsDep, verify_memoh_nl_gate_optional
from pb_studio.nl.gate_service import memoh_nl_gate

router = APIRouter(prefix="/integrations/memoh", tags=["integrations"])


class MemohNlGateRequest(BaseModel):
    telegram_chat_id: int
    message_id: int
    update_id: int | None = None
    text: str = ""
    raw_text: str = ""
    from_id: int | None = None
    is_mentioned: bool = False
    is_reply_to_bot: bool = False
    is_bot: bool = False


class MemohNlGateResponse(BaseModel):
    suppress_memoh_assistant: bool = False
    reason: str = ""


@router.post(
    "/nl-gate",
    response_model=MemohNlGateResponse,
    dependencies=[Depends(verify_memoh_nl_gate_optional)],
)
async def post_nl_gate(
    body: MemohNlGateRequest,
    session: DbSession,
    settings: SettingsDep,
) -> dict[str, Any]:
    out = await memoh_nl_gate(
        session,
        settings,
        telegram_chat_id=body.telegram_chat_id,
        message_id=body.message_id,
        update_id=body.update_id,
        text=body.text,
        raw_text=body.raw_text or body.text,
        from_id=body.from_id,
        is_mentioned=body.is_mentioned,
        is_reply_to_bot=body.is_reply_to_bot,
        is_bot=body.is_bot,
    )
    return {
        "suppress_memoh_assistant": bool(out.get("suppress_memoh_assistant")),
        "reason": str(out.get("reason") or ""),
    }
