from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator


def load_telegram_desktop_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON or encoding") from exc
    if not isinstance(data, dict):
        raise ValueError("root must be a JSON object")
    return data


def _parse_desktop_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.isdigit():
            try:
                return datetime.fromtimestamp(int(s), tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


_DESKTOP_FROM_ID = re.compile(r"^(user|bot|channel)(-?\d+)$", re.I)


def parse_desktop_from_id(from_id: Any) -> tuple[int | None, bool]:
    """Returns (telegram numeric id, is_channel_like). Channel ids kept as positive int from string."""
    if from_id is None:
        return None, False
    if isinstance(from_id, int):
        return from_id, False
    if isinstance(from_id, str):
        m = _DESKTOP_FROM_ID.match(from_id.strip())
        if not m:
            return None, False
        kind, num = m.group(1).lower(), m.group(2)
        try:
            n = int(num)
        except ValueError:
            return None, False
        if kind == "channel":
            return n, True
        return n, False
    return None, False


def _map_chat_type_to_api(export_type: str | None) -> str:
    if not export_type:
        return "unknown"
    t = str(export_type).lower()
    mapping = {
        "private_chat": "private",
        "personal_chat": "private",
        "bot_chat": "private",
        "group": "group",
        "supergroup": "supergroup",
        "channel": "channel",
    }
    return mapping.get(t, "unknown")


def iter_export_chat_dicts(root: dict[str, Any]) -> list[dict[str, Any]]:
    """Single-chat export or account export with chats.list / chats array."""
    if "messages" in root and isinstance(root["messages"], list):
        if "id" not in root:
            raise ValueError("single-chat export: missing chat id")
        return [root]
    chats_block = root.get("chats")
    if chats_block is None:
        raise ValueError("missing chats and not a single-chat export")
    if isinstance(chats_block, dict):
        lst = chats_block.get("list")
    elif isinstance(chats_block, list):
        lst = chats_block
    else:
        raise ValueError("invalid chats block")
    if not isinstance(lst, list):
        raise ValueError("chats list is not an array")
    out: list[dict[str, Any]] = []
    for item in lst:
        if isinstance(item, dict) and isinstance(item.get("messages"), list):
            out.append(item)
    return out


@dataclass(frozen=True)
class NormalizedMessage:
    telegram_message_id: int
    date: datetime
    text: str | None
    caption: str | None
    raw_bot_shaped: dict[str, Any]


@dataclass(frozen=True)
class NormalizedServiceEvent:
    date: datetime
    event_type: str
    actor_telegram_user_id: int | None
    actor_is_bot: bool | None
    raw_fragment: dict[str, Any]


def iter_chat_messages(
    chat_export: dict[str, Any],
    *,
    telegram_chat_id: int,
    chat_name: str | None,
    export_chat_type: str | None,
) -> Iterator[tuple[str, NormalizedMessage | NormalizedServiceEvent | None]]:
    """
    Yields ("msg" | "service" | "skip", payload).
    skip → unsupported / missing id / unparseable date.
    """
    messages = chat_export.get("messages") or []
    if not isinstance(messages, list):
        return
    api_chat_type = _map_chat_type_to_api(export_chat_type)
    title = chat_name or chat_export.get("name") or chat_export.get("title")

    for m in messages:
        if not isinstance(m, dict):
            yield "skip", None
            continue
        mid = m.get("id")
        if mid is None:
            yield "skip", None
            continue
        try:
            imid = int(mid)
        except (TypeError, ValueError):
            yield "skip", None
            continue
        dt = _parse_desktop_datetime(m.get("date"))
        if dt is None:
            yield "skip", None
            continue

        mtype = str(m.get("type") or "message").lower()
        if mtype == "service":
            action = m.get("action")
            et = f"telegram_desktop_service:{action}" if action else "telegram_desktop_service"
            actor_id, _ = parse_desktop_from_id(m.get("actor_id") or m.get("from_id"))
            yield (
                "service",
                NormalizedServiceEvent(
                    date=dt,
                    event_type=et[:64],
                    actor_telegram_user_id=actor_id,
                    actor_is_bot=None,
                    raw_fragment=dict(m),
                ),
            )
            continue

        if mtype != "message":
            yield "skip", None
            continue

        text = m.get("text")
        if text is not None and not isinstance(text, str):
            text = str(text) if text is not None else None
        caption = m.get("caption")
        if caption is not None and not isinstance(caption, str):
            caption = str(caption) if caption is not None else None

        from_id_raw = m.get("from_id")
        uid, _is_ch = parse_desktop_from_id(from_id_raw)
        from_name = m.get("from")
        from_display = from_name if isinstance(from_name, str) else None

        inner: dict[str, Any] = {
            "message_id": imid,
            "date": int(dt.timestamp()),
            "chat": {
                "id": telegram_chat_id,
                "type": api_chat_type,
                "title": title,
            },
            "studio_history_import": {"telegram_desktop_export": m},
        }
        if isinstance(text, str) and text:
            inner["text"] = text
        if isinstance(caption, str) and caption:
            inner["caption"] = caption
        if uid is not None:
            inner["from"] = {
                "id": uid,
                "is_bot": str(from_id_raw or "").lower().startswith("bot"),
                "first_name": (from_display or "")[:255] or "unknown",
            }

        yield (
            "msg",
            NormalizedMessage(
                telegram_message_id=imid,
                date=dt,
                text=inner.get("text"),
                caption=inner.get("caption"),
                raw_bot_shaped=inner,
            ),
        )
