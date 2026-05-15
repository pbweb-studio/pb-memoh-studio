from __future__ import annotations

from pb_studio.control_commands.parser import normalize_telegram_slash_command_token, parse_control_group_command_line
from pb_studio.core.config import Settings


_STUDIO_SLASH_PREFIXES = (
    "/summary",
    "/project",
    "/kb",
    "/rule",
)


def is_studio_slash_command_line(line: str) -> bool:
    """True if message is a Studio control-group slash command (incl. @bot suffix)."""
    raw = (line or "").strip()
    if not raw.startswith("/"):
        return False
    first = raw.split(None, 1)[0]
    norm = normalize_telegram_slash_command_token(first)
    if not any(norm.startswith(p) for p in _STUDIO_SLASH_PREFIXES):
        return False
    parsed = parse_control_group_command_line(raw)
    return parsed is not None


def strip_alias_prefix(text: str, settings: Settings) -> tuple[str, bool]:
    """If text starts with `alias,` (from STUDIO_NL_BOT_ALIASES), strip it."""
    s = (text or "").strip()
    low = s.lower()
    for tok in settings.studio_nl_bot_alias_prefixes_lower:
        prefix = tok + ","
        if low.startswith(prefix):
            rest = s[len(prefix) :].lstrip()
            return rest, True
    return s, False


def mentions_bot_in_text(text: str, bot_username_lower: str | None) -> bool:
    """Fallback if Memoh did not pass flags: check @username in text."""
    if not bot_username_lower:
        return False
    needle = "@" + bot_username_lower
    return needle in (text or "").lower()


_ENTITY_MENTION = "mention"


def raw_message_has_entity_mention_to_bot(raw: dict, bot_username_lower: str | None) -> bool:
    if not bot_username_lower:
        return False
    entities = raw.get("entities")
    if not isinstance(entities, list):
        return False
    text = str(raw.get("text") or raw.get("caption") or "")
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        if str(ent.get("type") or "").lower() != _ENTITY_MENTION:
            continue
        off = ent.get("offset")
        ln = ent.get("length")
        if not isinstance(off, int) or not isinstance(ln, int) or off < 0 or ln <= 0:
            continue
        if off + ln > len(text):
            continue
        frag = text[off : off + ln].lstrip("@").lower()
        if frag == bot_username_lower:
            return True
    return False
