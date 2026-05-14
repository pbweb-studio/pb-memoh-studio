from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def redact_secrets(message: str, bot_token: str | None) -> str:
    if not bot_token or not message:
        return message or ""
    if bot_token in message:
        return message.replace(bot_token, "***BOT_TOKEN***")
    return message


async def telegram_send_message(
    *,
    bot_token: str,
    chat_id: int,
    text: str,
    timeout_seconds: float,
) -> tuple[bool, int | None, str, int | None]:
    """POST sendMessage. Returns (ok, http_status, error_detail_redacted, telegram_message_id if ok). Never raises for HTTP/network."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:4090],
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(url, json=payload)
    except httpx.TimeoutException:
        return False, None, "timeout", None
    except httpx.RequestError as exc:
        return False, None, redact_secrets(str(exc), bot_token), None
    body_text = redact_secrets(resp.text, bot_token)
    try:
        data = resp.json()
    except json.JSONDecodeError:
        data = None
    if resp.status_code == 200 and isinstance(data, dict) and data.get("ok") is True:
        msg_id: int | None = None
        result = data.get("result")
        if isinstance(result, dict):
            raw_mid = result.get("message_id")
            if isinstance(raw_mid, int):
                msg_id = raw_mid
        return True, 200, "", msg_id
    detail = ""
    if isinstance(data, dict):
        desc = data.get("description")
        if isinstance(desc, str):
            detail = redact_secrets(desc, bot_token)
    if not detail and body_text:
        detail = body_text[:512]
    return False, resp.status_code, detail or f"http_{resp.status_code}", None
