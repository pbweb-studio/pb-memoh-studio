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
_SLUG_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$", re.IGNORECASE)


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


def _parse_project_command_line(line: str) -> ParsedControlCommand:
    parts = line.split()
    if not parts:
        return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "empty"})
    cmd = parts[0].strip().lower()
    rest = parts[1:]

    if cmd == "/project_help":
        return ParsedControlCommand(ControlCommandName.PROJECT_HELP, {})

    if cmd == "/project_list":
        if rest:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "project_list takes no arguments"})
        return ParsedControlCommand(ControlCommandName.PROJECT_LIST, {})

    if cmd == "/project_create":
        if len(rest) < 2:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "project_create needs slug and name"},
            )
        slug_t = rest[0].strip()
        if not _SLUG_TOKEN_RE.match(slug_t):
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_slug"})
        name = " ".join(rest[1:]).strip()
        if not name:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "empty_project_name"})
        return ParsedControlCommand(ControlCommandName.PROJECT_CREATE, {"slug": slug_t.lower(), "name": name})

    if cmd in ("/project_bind", "/project_unbind"):
        if len(rest) < 2:
            need = (
                "project_unbind needs project_slug and chat_uuid"
                if cmd == "/project_unbind"
                else "project_bind needs project_slug and chat_uuid"
            )
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": need})
        slug_t = rest[0].strip()
        if not _SLUG_TOKEN_RE.match(slug_t):
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_project_slug"})
        tid = str(_parse_uuid(rest[1]) or "")
        if not tid:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_chat_uuid"})
        if cmd == "/project_bind":
            return ParsedControlCommand(
                ControlCommandName.PROJECT_BIND,
                {"project_slug": slug_t.lower(), "chat_id": tid},
            )
        return ParsedControlCommand(
            ControlCommandName.PROJECT_UNBIND,
            {"project_slug": slug_t.lower(), "chat_id": tid},
        )

    if cmd == "/project_chats":
        if len(rest) != 1:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "project_chats needs project_slug"},
            )
        slug_t = rest[0].strip()
        if not _SLUG_TOKEN_RE.match(slug_t):
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_project_slug"})
        return ParsedControlCommand(ControlCommandName.PROJECT_CHATS, {"project_slug": slug_t.lower()})

    return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "unknown_project_command"})


def _parse_project_digest_command_line(line: str) -> ParsedControlCommand:
    parts = line.split()
    if not parts:
        return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "empty"})
    cmd = parts[0].strip().lower()
    rest = parts[1:]

    if cmd == "/project_digest_today":
        if len(rest) != 1:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "project_digest_today needs project_slug"},
            )
        slug_t = rest[0].strip()
        if not _SLUG_TOKEN_RE.match(slug_t):
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_project_slug"})
        return ParsedControlCommand(ControlCommandName.PROJECT_DIGEST_TODAY, {"project_slug": slug_t.lower()})

    if cmd == "/project_digest_yesterday":
        if len(rest) != 1:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "project_digest_yesterday needs project_slug"},
            )
        slug_t = rest[0].strip()
        if not _SLUG_TOKEN_RE.match(slug_t):
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_project_slug"})
        return ParsedControlCommand(ControlCommandName.PROJECT_DIGEST_YESTERDAY, {"project_slug": slug_t.lower()})

    if cmd == "/project_digest_latest":
        if len(rest) != 1:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "project_digest_latest needs project_slug"},
            )
        slug_t = rest[0].strip()
        if not _SLUG_TOKEN_RE.match(slug_t):
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_project_slug"})
        return ParsedControlCommand(ControlCommandName.PROJECT_DIGEST_LATEST, {"project_slug": slug_t.lower()})

    if cmd == "/project_digest_period":
        if len(rest) != 3:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "project_digest_period needs project_slug and two YYYY-MM-DD"},
            )
        slug_t = rest[0].strip()
        if not _SLUG_TOKEN_RE.match(slug_t):
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_project_slug"})
        da = _parse_iso_date(rest[1])
        db = _parse_iso_date(rest[2])
        if da is None or db is None:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_date_format"})
        return ParsedControlCommand(
            ControlCommandName.PROJECT_DIGEST_PERIOD,
            {"project_slug": slug_t.lower(), "date_a": rest[1].strip(), "date_b": rest[2].strip()},
        )

    return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "unknown_project_digest_command"})


def _parse_kb_command_line(line: str) -> ParsedControlCommand:
    parts = line.split(maxsplit=1)
    if not parts:
        return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "empty"})
    cmd = parts[0].strip().lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/kb_help":
        if rest:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "kb_help takes no arguments"})
        return ParsedControlCommand(ControlCommandName.KB_HELP, {})

    if cmd == "/kb_list":
        if rest:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "kb_list takes no arguments"})
        return ParsedControlCommand(ControlCommandName.KB_LIST, {})

    if cmd == "/kb_get":
        if not rest:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "kb_get needs document_uuid"},
            )
        uid = _parse_uuid(rest)
        if uid is None:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_document_uuid"})
        return ParsedControlCommand(ControlCommandName.KB_GET, {"document_id": str(uid)})

    if cmd == "/kb_parse":
        if not rest:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "kb_parse needs document_uuid"},
            )
        uid = _parse_uuid(rest)
        if uid is None:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_document_uuid"})
        return ParsedControlCommand(ControlCommandName.KB_PARSE, {"document_id": str(uid)})

    if cmd == "/kb_status":
        if not rest:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "kb_status needs document_uuid"},
            )
        uid = _parse_uuid(rest)
        if uid is None:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_document_uuid"})
        return ParsedControlCommand(ControlCommandName.KB_STATUS, {"document_id": str(uid)})

    if cmd == "/kb_search":
        if not rest:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "kb_search needs query (optionally: --project <slug> ...)"},
            )
        rlow = rest.lower()
        m = re.match(r"(?i)--project\s+", rest)
        if m:
            after = rest[m.end() :].strip()
            parts_slug = after.split(maxsplit=1)
            if len(parts_slug) < 2:
                return ParsedControlCommand(
                    ControlCommandName.UNKNOWN,
                    {"raw": line, "reason": "kb_search --project needs slug and query"},
                )
            slug_t = parts_slug[0].strip()
            if not _SLUG_TOKEN_RE.match(slug_t):
                return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_project_slug"})
            q = parts_slug[1].strip()
            if not q:
                return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "kb_search empty query"})
            return ParsedControlCommand(
                ControlCommandName.KB_SEARCH,
                {"project_slug": slug_t.lower(), "query": q},
            )
        return ParsedControlCommand(ControlCommandName.KB_SEARCH, {"project_slug": "", "query": rest.strip()})

    if cmd == "/kb_ask":
        if not rest:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "kb_ask needs question (optionally: --project <slug> ...)"},
            )
        m = re.match(r"(?i)--project\s+", rest)
        if m:
            after = rest[m.end() :].strip()
            parts_slug = after.split(maxsplit=1)
            if len(parts_slug) < 2:
                return ParsedControlCommand(
                    ControlCommandName.UNKNOWN,
                    {"raw": line, "reason": "kb_ask --project needs slug and question"},
                )
            slug_t = parts_slug[0].strip()
            if not _SLUG_TOKEN_RE.match(slug_t):
                return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "invalid_project_slug"})
            q = parts_slug[1].strip()
            if not q:
                return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "kb_ask empty question"})
            return ParsedControlCommand(
                ControlCommandName.KB_ASK,
                {"project_slug": slug_t.lower(), "query": q},
            )
        return ParsedControlCommand(ControlCommandName.KB_ASK, {"project_slug": "", "query": rest.strip()})

    if cmd == "/kb_add":
        sep = " | "
        if sep not in rest:
            return ParsedControlCommand(
                ControlCommandName.UNKNOWN,
                {"raw": line, "reason": "kb_add needs: title | text (разделитель « пробел | пробел »)"},
            )
        title, text = rest.split(sep, 1)
        title = title.strip()
        text = text.strip()
        if not title:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "kb_add empty title"})
        if not text:
            return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "kb_add empty text"})
        return ParsedControlCommand(ControlCommandName.KB_ADD, {"title": title, "text": text})

    return ParsedControlCommand(ControlCommandName.UNKNOWN, {"raw": line, "reason": "unknown_kb_command"})


def parse_control_group_command_line(text: str | None) -> ParsedControlCommand | None:
    """
    Разобрать строку сообщения из control group.
    Возвращает None, если это не команда /summary_* или /project* или /kb_*.
    """
    if not text or not isinstance(text, str):
        return None
    line = text.strip()
    if line.startswith("/kb"):
        return _parse_kb_command_line(line)
    if line.startswith("/project_digest"):
        return _parse_project_digest_command_line(line)
    if line.startswith("/project"):
        return _parse_project_command_line(line)
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
