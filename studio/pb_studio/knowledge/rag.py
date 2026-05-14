"""RAG question answering over KB chunks (phase 10e). Chat completion only — no Memoh."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from pb_studio.core.config import Settings
from pb_studio.knowledge.constants import (
    KNOWLEDGE_RAG_NOT_FOUND_ANSWER,
    KnowledgeChatProviderKind,
)
from pb_studio.knowledge.embeddings import redact_embedding_error
from pb_studio.knowledge.service import KnowledgeSearchHit, search_knowledge_chunks


def _chat_completions_url(base_url: str) -> str:
    b = (base_url or "").strip().rstrip("/")
    if not b:
        raise ValueError("empty STUDIO_KB_CHAT_API_BASE_URL")
    if b.endswith("/chat/completions"):
        return b
    return f"{b}/chat/completions"


def _build_context_from_hits(hits: list[KnowledgeSearchHit], max_chars: int) -> str:
    parts: list[str] = []
    used = 0
    for h in hits:
        block = f"[document_id={h.document_id} chunk_id={h.chunk_id}]\n{h.content_text}"
        sep = 2
        if used + len(block) + sep > max_chars:
            remain = max_chars - used - sep
            if remain > 80:
                parts.append(block[:remain] + "\n…")
            break
        parts.append(block)
        used += len(block) + sep
    return "\n\n".join(parts)


async def _openai_compatible_chat(
    settings: Settings,
    *,
    system_prompt: str,
    user_prompt: str,
) -> str:
    raw_provider = (settings.studio_kb_chat_provider or "").strip().lower()
    if raw_provider != KnowledgeChatProviderKind.OPENAI_COMPATIBLE:
        raise ValueError(f"unsupported STUDIO_KB_CHAT_PROVIDER: {raw_provider!r}")
    base = (settings.studio_kb_chat_api_base_url or "").strip()
    key = (settings.studio_kb_chat_api_key or "").strip()
    model = (settings.studio_kb_chat_model or "").strip()
    if not base or not key:
        raise ValueError("STUDIO_KB_CHAT_API_BASE_URL and STUDIO_KB_CHAT_API_KEY must be set for RAG with sources")
    if not model:
        raise ValueError("STUDIO_KB_CHAT_MODEL must be set for RAG with sources")

    url = _chat_completions_url(base)
    timeout = httpx.Timeout(max(settings.studio_kb_chat_timeout_ms, 3000) / 1000.0)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise RuntimeError("chat completion timeout") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"chat completion request error: {type(exc).__name__}") from exc

    body_preview = redact_embedding_error(resp.text[:2500], key)
    if resp.status_code != 200:
        raise RuntimeError(f"chat HTTP {resp.status_code}: {body_preview}")

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("chat completion: invalid JSON response") from exc

    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("chat completion: missing choices[]")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("chat completion: invalid choice")
    msg = first.get("message")
    if not isinstance(msg, dict):
        raise RuntimeError("chat completion: missing message")
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("chat completion: empty content")
    return content.strip()


@dataclass(frozen=True)
class KnowledgeRagResult:
    answer: str
    sources: list[KnowledgeSearchHit]


async def ask_knowledge_base(
    session: AsyncSession,
    settings: Settings,
    *,
    question: str,
    project_id: UUID | None = None,
) -> KnowledgeRagResult:
    """
    Retrieval по KB + один вызов chat completion.
    Без источников (пустой vector search) — ответ KNOWLEDGE_RAG_NOT_FOUND_ANSWER без вызова LLM.
    """
    q = (question or "").strip()
    if not q:
        raise ValueError("empty question")

    hits = await search_knowledge_chunks(
        session,
        settings,
        query=q,
        project_id=project_id,
        top_k=settings.studio_kb_rag_top_k,
    )
    if not hits:
        return KnowledgeRagResult(answer=KNOWLEDGE_RAG_NOT_FOUND_ANSWER, sources=[])

    context = _build_context_from_hits(hits, settings.studio_kb_rag_max_context_chars)
    system_prompt = (
        "Ты отвечаешь только на основе фрагментов базы знаний в сообщении пользователя. "
        "Если в фрагментах нет достаточной информации для ответа на вопрос, ответь ровно одной фразой: "
        f"«{KNOWLEDGE_RAG_NOT_FOUND_ANSWER}». Не выдумывай факты вне этих фрагментов. Отвечай кратко по-русски."
    )
    user_prompt = f"Фрагменты базы знаний:\n\n{context}\n\nВопрос: {q}"

    secret = (settings.studio_kb_chat_api_key or "").strip() or None
    try:
        answer = await _openai_compatible_chat(settings, system_prompt=system_prompt, user_prompt=user_prompt)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(redact_embedding_error(str(exc), secret)) from exc

    return KnowledgeRagResult(answer=answer, sources=hits)
