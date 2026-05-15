from __future__ import annotations

import re

from pb_studio.control_commands.parser import normalize_telegram_slash_command_token, parse_control_group_command_line
from pb_studio.core.config import Settings

# Telegram @username: 5–32 [A-Za-z0-9_]; допускаем 4+ для совместимости с тестовыми ботами.
_LEADING_MENTION_RE = re.compile(r"^@[A-Za-z0-9_]{4,32}\s+")
# Иногда после @username нет ASCII-пробела (NBSP/NNBSP или сразу кириллица) — иначе роутер не видит «запомни».
_LEADING_MENTION_RE_LOOSE = re.compile(
    r"^@[A-Za-z0-9_]{4,32}(?:[\s\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+|(?=[\u0400-\u04ffЁё]))"
)
_BIDI_AND_BOM = re.compile(r"^[\ufeff\u200e\u200f\u202a-\u202e]+")


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


def strip_leading_bot_mentions(text: str) -> str:
    """Remove one or more leading @username tokens (Telegram text mentions)."""
    s = (text or "").strip()
    s = _BIDI_AND_BOM.sub("", s)
    while True:
        m = _LEADING_MENTION_RE.match(s) or _LEADING_MENTION_RE_LOOSE.match(s)
        if not m:
            break
        s = s[m.end() :].lstrip()
    return s.strip()


def normalize_nl_router_input(text: str, settings: Settings) -> str:
    """Text for NL router: strip Jarvis-style alias prefix, then leading @bot mentions."""
    s = (text or "").strip()
    s, _ = strip_alias_prefix(s, settings)
    s = strip_leading_bot_mentions(s)
    return s.strip()


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
