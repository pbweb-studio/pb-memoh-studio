"""Dialect-specific storage for KB chunk embeddings (pgvector on Postgres, JSON list on SQLite)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator


class EmbeddingVectorType(TypeDecorator[list[float] | None]):
    """Postgres: pgvector.Vector(dim). SQLite/tests: JSON array of floats."""

    cache_ok = True
    impl = JSON(none_as_null=True)

    def __init__(self, dim: int) -> None:
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_bind_param(self, value: list[float] | None, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return list(value)

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            if isinstance(value, list):
                return [float(x) for x in value]
            return [float(x) for x in list(value)]
        if isinstance(value, list):
            return [float(x) for x in value]
        return None
