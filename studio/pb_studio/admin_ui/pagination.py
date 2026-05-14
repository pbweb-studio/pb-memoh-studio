"""Shared pagination helpers for Studio Admin UI (GET list pages)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def clamp_limit(limit: int | None) -> int:
    return min(max(int(limit or DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)


def clamp_page(page: int | None) -> int:
    return max(int(page or 1), 1)


def total_pages(total: int, limit: int) -> int:
    if total <= 0:
        return 1
    return max((total + limit - 1) // limit, 1)


def effective_page(page: int, total: int, limit: int) -> int:
    tp = total_pages(total, limit)
    return min(max(page, 1), tp)


def offset_for(page_eff: int, limit: int) -> int:
    return (page_eff - 1) * limit


@dataclass(frozen=True)
class PaginationUrls:
    page: int
    limit: int
    total: int
    total_pages: int
    prev_url: str | None
    next_url: str | None
    show: bool


def build_pagination_urls(
    *,
    base_path: str,
    page: int,
    limit: int,
    total: int,
    extra_query: dict[str, Any],
) -> PaginationUrls:
    """Build prev/next URLs preserving filter query params (page is updated)."""
    tp = total_pages(total, limit)
    page_eff = effective_page(page, total, limit)
    flat: dict[str, str] = {}
    for key, val in extra_query.items():
        if val is None or val == "":
            continue
        flat[str(key)] = str(val)

    def url_for(p: int) -> str:
        q = {**flat, "page": str(p), "limit": str(limit)}
        return f"{base_path}?{urlencode(q)}"

    prev_url = url_for(page_eff - 1) if page_eff > 1 else None
    next_url = url_for(page_eff + 1) if page_eff < tp else None
    show = total > 0 or bool(flat)
    return PaginationUrls(
        page=page_eff,
        limit=limit,
        total=total,
        total_pages=tp,
        prev_url=prev_url,
        next_url=next_url,
        show=show,
    )
