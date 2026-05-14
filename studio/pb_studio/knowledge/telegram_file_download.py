"""Telegram Bot API: getFile + download (bounded). Phase 10g — KB import from control group."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from pb_studio.control_group.telegram_outbound import redact_secrets


async def telegram_fetch_file_bytes(
    bot_token: str,
    file_id: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
) -> tuple[bool, bytes | None, str, str]:
    """
    GET getFile → GET file from api.telegram.org/file/bot<token>/<path>.
    Returns (ok, data_or_none, error_detail_redacted, suggested_basename).
    suggested_basename from Telegram file_path (for extension), or "telegram.bin".
    Never raises for HTTP/network.
    """
    token = (bot_token or "").strip()
    fid = (file_id or "").strip()
    if not token or not fid:
        return False, None, "missing_token_or_file_id", "telegram.bin"
    if max_bytes <= 0:
        return False, None, "invalid_max_bytes", "telegram.bin"

    get_url = f"https://api.telegram.org/bot{token}/getFile"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.get(get_url, params={"file_id": fid})
    except httpx.TimeoutException:
        return False, None, "getFile_timeout", "telegram.bin"
    except httpx.RequestError as exc:
        return False, None, redact_secrets(str(exc), token)[:500], "telegram.bin"

    body_text = redact_secrets(resp.text, token)
    try:
        data: Any = resp.json()
    except json.JSONDecodeError:
        data = None

    if resp.status_code != 200 or not isinstance(data, dict) or data.get("ok") is not True:
        detail = ""
        if isinstance(data, dict):
            desc = data.get("description")
            if isinstance(desc, str):
                detail = redact_secrets(desc, token)
        if not detail and body_text:
            detail = body_text[:512]
        return False, None, detail or f"getFile_http_{resp.status_code}", "telegram.bin"

    result = data.get("result")
    if not isinstance(result, dict):
        return False, None, "getFile_invalid_result", "telegram.bin"
    file_path = result.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return False, None, "getFile_missing_file_path", "telegram.bin"
    basename = Path(file_path.replace("\\", "/")).name or "telegram.bin"

    fsize = result.get("file_size")
    if isinstance(fsize, int) and fsize > max_bytes:
        return False, None, "file_size_exceeds_limit", basename

    file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    buf = bytearray()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            async with client.stream("GET", file_url) as dl:
                if dl.status_code != 200:
                    raw = await dl.aread()
                    txt = redact_secrets(raw[:512].decode("utf-8", errors="replace"), token)
                    return False, None, txt or f"download_http_{dl.status_code}", basename
                cl = dl.headers.get("content-length")
                if cl is not None:
                    try:
                        if int(cl) > max_bytes:
                            return False, None, "content_length_exceeds_limit", basename
                    except ValueError:
                        pass
                async for chunk in dl.aiter_bytes():
                    if not chunk:
                        continue
                    if len(buf) + len(chunk) > max_bytes:
                        return False, None, "download_exceeds_max_bytes", basename
                    buf.extend(chunk)
    except httpx.TimeoutException:
        return False, None, "download_timeout", basename
    except httpx.RequestError as exc:
        return False, None, redact_secrets(str(exc), token)[:500], basename

    return True, bytes(buf), "", basename
