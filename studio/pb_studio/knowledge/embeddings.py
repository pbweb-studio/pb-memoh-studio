"""KB embedding providers (phase 10c). No LLM/chat — deterministic vector for Studio."""

from __future__ import annotations

import hashlib
import math
import struct

from pb_studio.core.config import Settings
from pb_studio.knowledge.constants import KNOWLEDGE_EMBEDDING_VECTOR_DIM


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


class DeterministicEmbeddingProvider:
    """Default provider: no external HTTP, no LLM."""

    def __init__(self, *, model_label: str = "deterministic") -> None:
        self.model_label = model_label

    async def embed_one(self, text: str) -> list[float]:
        return deterministic_unit_vector(text, KNOWLEDGE_EMBEDDING_VECTOR_DIM)


def get_embedding_provider(settings: Settings) -> DeterministicEmbeddingProvider:
    """Phase 10c: only deterministic provider (no external API)."""
    return DeterministicEmbeddingProvider(model_label=settings.studio_kb_embedding_model or "deterministic")
