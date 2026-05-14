from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from pb_studio.api.deps import DbSession, SettingsDep, verify_admin_optional
from pb_studio.control_commands.schemas import ControlCommandOut, ControlCommandsProcessResponse
from pb_studio.control_commands.service import list_control_commands, run_control_commands_cycle

router = APIRouter(prefix="/control-commands", tags=["control-commands"])


@router.get("", response_model=list[ControlCommandOut], dependencies=[Depends(verify_admin_optional)])
async def get_control_commands(
    session: DbSession,
    status: str | None = Query(default=None, description="Фильтр по status"),
    command_name: str | None = Query(default=None, description="Фильтр по command_name"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ControlCommandOut]:
    rows = await list_control_commands(session, status=status, command_name=command_name, limit=limit)
    return [ControlCommandOut.model_validate(r) for r in rows]


@router.post(
    "/process-pending",
    response_model=ControlCommandsProcessResponse,
    dependencies=[Depends(verify_admin_optional)],
)
async def post_process_pending_control_commands(
    session: DbSession,
    settings: SettingsDep,
) -> ControlCommandsProcessResponse:
    out = await run_control_commands_cycle(session, settings)
    return ControlCommandsProcessResponse(scan=out["scan"], process=out["process"])
