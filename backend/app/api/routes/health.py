from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import DbSession, EmbedderDep, LLMDep, SettingsDep

router = APIRouter(tags=["system"])


@router.get("/health", summary="Service health and active providers")
def health(db: DbSession, settings: SettingsDep, embedder: EmbedderDep, llm: LLMDep) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": __version__,
        "database": {"status": database, "dialect": db.get_bind().dialect.name},
        "vector_store": "pgvector" if settings.is_postgres else "in-process (numpy + BM25)",
        "llm": {"provider": llm.name, "model": llm.model},
        "embeddings": {"provider": embedder.name, "model": embedder.model, "dim": embedder.dim},
        "limits": {"max_upload_mb": settings.max_upload_mb},
    }
