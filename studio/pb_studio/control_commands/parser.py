from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from pb_studio.control_commands.constants import ControlCommandName


@dataclass
class ParsedControlCommand:
    name: str
    args: dict[str, str | list[str]]


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_uuid(token: str) -> UUID | None:
    t = token.strip()
    if not _UUID_RE.match(t):
        return None
    try:
        return UUID(t)
    except ValueError:
        return None


def _parse_iso_date(s: str) -> date | None:
    s = s.strip()
    if not _DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_control_group_command_line(text: str | None) -> ParsedControlCommand | None:
    """
    Разобрать строку сообщения из control group.
    Возвращает None, если это не команда /summary_*.
    """
    if not text or not isinstance(text, str):
        return None
    line = text.strip()
    if not line.startswith("/summary"):
        return None

    parts = line.split()
    if not parts:
        return None
    cmd = parts[0].strip().lower()
    rest = parts[1:]

    if cmd == "/summary_help":
        return ParsedControlCommand(ControlCommandName.SUMMARY_HELP, {})

    if cmd == "/summary_chats":
        if rest:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "summary_chats takes no arguments"})
        return ParsedControlCommand(ControlCommandName.SUMMARY_CHATS, {})

    if cmd == "/summary_all_today":
        if rest:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "summary_all_today takes no arguments"})
        return ParsedControlCommand(ControlCommandName.SUMMARY_ALL_TODAY, {})

    if cmd == "/summary_all_yesterday":
        if rest:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "summary_all_yesterday takes no arguments"})
        return ParsedControlCommand(ControlCommandName.SUMMARY_ALL_YESTERDAY, {})

    if cmd == "/summary_today":
        if len(rest) < 1:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "missing_chat_uuid"})
        tid = str(_parse_uuid(rest[0]) or "")
        if not tid:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_chat_uuid"})
        return ParsedControlCommand(ControlCommandName.SUMMARY_TODAY, {"target_chat_id": tid})

    if cmd == "/summary_yesterday":
        if len(rest) < 1:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "missing_chat_uuid"})
        tid = str(_parse_uuid(rest[0]) or "")
        if not tid:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_chat_uuid"})
        return ParsedControlCommand(ControlCommandName.SUMMARY_YESTERDAY, {"target_chat_id": tid})

    if cmd == "/summary_latest":
        if len(rest) < 1:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "missing_chat_uuid"})
        tid = str(_parse_uuid(rest[0]) or "")
        if not tid:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_chat_uuid"})
        return ParsedControlCommand(ControlCommandName.SUMMARY_LATEST, {"target_chat_id": tid})

    if cmd == "/summary_period":
        if len(rest) < 3:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "summary_period needs chat_uuid and two YYYY-MM-DD"},
            )
        tid = str(_parse_uuid(rest[0]) or "")
        if not tid:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_chat_uuid"})
        da = _parse_iso_date(rest[1])
        db = _parse_iso_date(rest[2])
        if da is None or db is None:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_date_format"})
        return ParsedControlCommand(
            ControlCommandName.SUMMARY_PERIOD,
            {"target_chat_id": tid, "date_a": rest[1].strip(), "date_b": rest[2].strip()},
        )

    return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "unknown_command"})


def period_bounds_utc(date_a: str, date_b: str) -> tuple[datetime, datetime]:
    da = _parse_iso_date(date_a)
    db = _parse_iso_date(date_b)
    if da is None or db is None:
        raise ValueError("invalid date")
    start = datetime.combine(da, time.min, tzinfo=timezone.utc)
    end = datetime.combine(db + timedelta(days=1), time.min, tzinfo=timezone.utc)
    if end <= start:
        raise ValueError("period_end must be after period_start")
    return start, end
