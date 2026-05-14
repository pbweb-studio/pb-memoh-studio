"""KB embedding providers: deterministic (tests/local) and OpenAI-compatible HTTP (phase 10d)."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from typing import Any, Protocol, runtime_checkable

import httpx

from pb_studio.control_group.telegram_outbound import redact_secrets
from pb_studio.core.config import Settings
from pb_studio.knowledge.constants import (
    KNOWLEDGE_EMBEDDING_VECTOR_DIM,
    KnowledgeEmbeddingProviderKind,
)


def redact_embedding_error(message: str, api_key: str | None) -> str:
    """Не допускаем утечки ключа в last_error / логах."""
    return redact_secrets(message or "", api_key)


def deterministic_unit_vector(text: str, dim: int) -> list[float]:
    """Reproducible L2-normalized vector from text (same dim as DB column)."""
    if dim <= 0:
        return []
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    out: list[float] = []
    block = bytearray(seed)
    while len(out) < dim:
        for i in range(0, len(block) - 7, 8):
            q = struct.unpack_from("<Q", block, i)[0]
            out.append((q / (2**64)) * 2.0 - 1.0)
            if len(out) >= dim:
                break
        block = bytearray(hashlib.sha256(block).digest())
    s = math.sqrt(sum(x * x for x in out))
    if s <= 0:
        return [0.0] * dim
    return [x / s for x in out]


def _embeddings_post_url(base_url: str) -> str:
    b = (base_url or "").strip().rstrip("/")
    if not b:
        raise ValueError("empty STUDIO_KB_EMBEDDING_API_BASE_URL")
    if b.endswith("/embeddings"):
        return b
    return f"{b}/embeddings"


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Провайдер эмбеддингов для KB (без LLM chat)."""

    model_label: str
    batch_atomic: bool

    async def embed_one(self, text: str) -> list[float]: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicEmbeddingProvider:
    """Локальный провайдер без внешнего HTTP."""

    batch_atomic = False

    def __init__(self, *, model_label: str = "deterministic") -> None:
        self.model_label = model_label

    async def embed_one(self, text: str) -> list[float]:
        return deterministic_unit_vector(text, KNOWLEDGE_EMBEDDING_VECTOR_DIM)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_one(t) for t in texts]


class OpenaiCompatibleEmbeddingProvider:
    """POST …/embeddings (OpenAI-compatible). Один HTTP-запрос на батч (batch_atomic)."""

    batch_atomic = True

    def __init__(self, settings: Settings) -> None:
        self.model_label = settings.studio_kb_embedding_model or "text-embedding-3-small"
        self._base = (settings.studio_kb_embedding_api_base_url or "").strip()
        self._api_key = (settings.studio_kb_embedding_api_key or "").strip()
        self._timeout = max(settings.studio_kb_embedding_timeout_ms, 500) / 1000.0

    async def embed_one(self, text: str) -> list[float]:
        vecs = await self.embed_texts([text])
        return vecs[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._api_key or not self._base:
            raise ValueError(
                "openai_compatible: задайте STUDIO_KB_EMBEDDING_API_BASE_URL и STUDIO_KB_EMBEDDING_API_KEY",
            )
        url = _embeddings_post_url(self._base)
        payload: dict[str, Any] = {"model": self.model_label, "input": texts}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self._timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise RuntimeError("embeddings request timeout") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"embeddings request error: {type(exc).__name__}") from exc

        body_preview = redact_embedding_error(resp.text[:2000], self._api_key)
        if resp.status_code != 200:
            raise RuntimeError(f"embeddings HTTP {resp.status_code}: {body_preview}")

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("embeddings: invalid JSON response") from exc

        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("embeddings: missing data[] in response")

        indexed: list[tuple[int, list[float]]] = []
        for j, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if not isinstance(idx, int):
                idx = j
            emb = item.get("embedding")
            if not isinstance(emb, list):
                continue
            floats = [float(x) for x in emb]
            indexed.append((idx, floats))

        indexed.sort(key=lambda x: x[0])
        vectors = [v for _, v in indexed]
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"embeddings: expected {len(texts)} vectors, got {len(vectors)}",
            )
        for vec in vectors:
            if len(vec) != KNOWLEDGE_EMBEDDING_VECTOR_DIM:
                raise ValueError(
                    f"embedding dim mismatch: got {len(vec)}, expected {KNOWLEDGE_EMBEDDING_VECTOR_DIM}",
                )
        return vectors


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    raw = (settings.studio_kb_embedding_provider or KnowledgeEmbeddingProviderKind.DETERMINISTIC).strip().lower()
    if raw in ("", KnowledgeEmbeddingProviderKind.DETERMINISTIC):
        return DeterministicEmbeddingProvider(model_label=settings.studio_kb_embedding_model or "deterministic")
    if raw == KnowledgeEmbeddingProviderKind.OPENAI_COMPATIBLE:
        return OpenaiCompatibleEmbeddingProvider(settings)
    raise ValueError(f"unknown STUDIO_KB_EMBEDDING_PROVIDER: {raw!r}")
