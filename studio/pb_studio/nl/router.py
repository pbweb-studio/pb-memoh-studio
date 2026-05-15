from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from pb_studio.core.config import Settings
from pb_studio.nl.router_deterministic import route_deterministic
from pb_studio.nl.schemas import NLRouterDecision
from pb_studio.nl.turn_input import nl_turn_router_input

logger = logging.getLogger(__name__)


def _chat_url(base_url: str) -> str:
    b = (base_url or "").strip().rstrip("/")
    if not b:
        raise ValueError("empty STUDIO_NL_ROUTER_API_BASE_URL")
    if b.endswith("/chat/completions"):
        return b
    return f"{b}/chat/completions"


_ROUTER_SYSTEM = """You are a strict JSON router for a studio control bot. Output a single JSON object only, no markdown.
Allowed top-level keys: mode (business_action|learning|clarify|casual|refusal|error), intent (studio_digest|project_digest|open_risks_or_sla|list_chats|list_projects|kb_search|kb_ask|diagnostics_status|help_capabilities|runtime_config_query|learning_request|casual_or_assistant|unclear|null), confidence (0..1), parameters (object), needs_confirmation (boolean), clarify_question (string|null), learning_type (string|null for learning_request), suggested_text (string|null).
Never invent facts or SQL. If unsure, mode=clarify intent=unclear with a short Russian question in clarify_question.
Current user message is in Russian or English."""


async def route_nl(settings: Settings, text: str) -> NLRouterDecision:
    normalized = nl_turn_router_input(text, settings)
    prov = (settings.studio_nl_router_provider or "").strip().lower()
    if prov != "openai_compatible":
        return route_deterministic(normalized)

    base = (settings.studio_nl_router_api_base_url or "").strip()
    key = (settings.studio_nl_router_api_key or "").strip()
    model = (settings.studio_nl_router_model or "").strip()
    if settings.studio_nl_router_reuse_kb_chat_provider:
        base = base or (settings.studio_kb_chat_api_base_url or "").strip()
        key = key or (settings.studio_kb_chat_api_key or "").strip()
        model = model or (settings.studio_kb_chat_model or "").strip()

    if not base or not key or not model:
        logger.warning("NL openai_compatible router: CONFIG_REQUIRED (missing url/key/model)")
        return route_deterministic(normalized)

    try:
        return await _call_openai_router(settings, normalized, base_url=base, api_key=key, model=model)
    except (httpx.HTTPError, json.JSONDecodeError, ValidationError, KeyError, ValueError, TypeError) as exc:
        logger.warning("NL openai router failed: %s", exc)
        return route_deterministic(normalized)


async def _call_openai_router(
    settings: Settings,
    text: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> NLRouterDecision:
    url = _chat_url(base_url)
    timeout = httpx.Timeout(max(settings.studio_nl_router_timeout_ms, 3000) / 1000.0)
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _ROUTER_SYSTEM},
            {"role": "user", "content": text[:8000]},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    content = (((data or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"router json: {exc}") from exc
    try:
        return NLRouterDecision.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"router schema: {exc}") from exc
