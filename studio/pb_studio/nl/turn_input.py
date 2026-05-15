"""Один NL-turn: очистка user-текста от цитат/префиксов до роутинга (без истории studio_messages)."""

from __future__ import annotations

import re

from pb_studio.core.config import Settings
from pb_studio.nl.triggers import normalize_nl_router_input

# Ведущие «оформленные» цитаты / reply-префиксы (только префикс сообщения).
_BLOCKQUOTE_LINE = re.compile(r"^\s*>\s?")


def strip_reply_decorations(text: str) -> str:
    """
    Убрать ведущие блоки, которые часто тащат текст предыдущего ответа бота в новый user message.
    Консервативно: только с начала строки, до первой «нормальной» строки.
    """
    s = (text or "").strip()
    if not s:
        return ""
    lines = s.split("\n")
    idx = 0
    n = len(lines)
    while idx < n:
        line = lines[idx]
        stripped_line = line.strip()
        if stripped_line == "":
            idx += 1
            continue
        if _BLOCKQUOTE_LINE.match(line):
            idx += 1
            continue
        low_sq = stripped_line.lower()
        if low_sq.startswith("[reply") and stripped_line.endswith("]"):
            idx += 1
            continue
        break
    return "\n".join(lines[idx:]).strip()


def nl_turn_router_input(text: str, settings: Settings) -> str:
    """Текущий user turn для NL: без reply-цитат, затем alias + @mentions."""
    cleaned = strip_reply_decorations(text)
    return normalize_nl_router_input(cleaned, settings)
