"""Column types that behave the same on PostgreSQL (production) and SQLite (tests)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine

JSONType = JSON().with_variant(JSONB(), "postgresql")


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetime, always returned in UTC. SQLite drops tzinfo (re-attached here) and
    PostgreSQL returns values in the connection's TimeZone (converted here)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EmbeddingVector(TypeDecorator[np.ndarray]):
    """pgvector ``vector(dim)`` on PostgreSQL, a JSON float array everywhere else."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        return [float(x) for x in value]

    def process_result_value(self, value: Any, dialect: Dialect) -> np.ndarray | None:
        if value is None:
            return None
        return np.asarray(value, dtype=np.float32)
