"""Application settings, loaded from environment variables and an optional .env file."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App -----------------------------------------------------------------
    app_name: str = "AI Course Assistant"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    # NoDecode: accept "a,b" from the environment instead of requiring a JSON array.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Optional shared secret between the Next.js server-side proxy and this API. When set, every /api route
    # except /api/health requires "Authorization: Bearer <token>", so the API can't be called around the proxy.
    app_api_token: SecretStr | None = None

    # --- Storage ---------------------------------------------------------------
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/course_assistant"
    # Run Alembic migrations on startup (handy locally; the Docker image migrates before starting).
    auto_migrate: bool = True
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    # Materials for the one-click demo course (POST /api/demo).
    demo_dir: Path = BACKEND_DIR.parent / "sample_data"
    max_upload_mb: int = 25
    # Guards against pathological uploads (huge decks, zip bombs, text dumps).
    max_pages: int = 500
    max_document_chars: int = 2_000_000
    max_unzipped_mb: int = 200

    # --- LLM -------------------------------------------------------------------
    # "auto" picks anthropic if ANTHROPIC_API_KEY is set, then openai if
    # OPENAI_API_KEY is set, and otherwise falls back to the offline provider.
    llm_provider: Literal["auto", "anthropic", "openai", "offline"] = "auto"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    # Leave blank for models without effort support (e.g. Haiku).
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = "medium"
    anthropic_fallbacks: bool = True
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    llm_timeout_seconds: float = 120.0

    # --- Embeddings ------------------------------------------------------------
    embedding_provider: Literal["fastembed", "openai", "hash"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_batch_size: int = 32
    model_cache_dir: Path = BACKEND_DIR / "data" / "models"

    # --- Chunking & retrieval -------------------------------------------------
    chunk_size: int = 1000
    chunk_overlap: int = 150
    retrieval_top_k: int = 6
    retrieval_candidates: int = 30
    rrf_k: int = 60
    max_context_chars: int = 14000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator(
        "anthropic_api_key",
        "anthropic_effort",
        "openai_api_key",
        "openai_base_url",
        "openai_model",
        "app_api_token",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def resolved_llm_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key and self.openai_model:
            return "openai"
        return "offline"


@lru_cache
def get_settings() -> Settings:
    return Settings()
