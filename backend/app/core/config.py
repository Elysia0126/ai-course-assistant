"""Application settings, loaded from environment variables and an optional .env file."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
_RATE_SPEC = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


@dataclass(frozen=True)
class RateRule:
    """At most ``limit`` requests per ``window`` seconds."""

    limit: int
    window: int


def parse_rate(spec: str) -> RateRule:
    match = _RATE_SPEC.match(spec)
    if not match or int(match.group(1)) < 1 or int(match.group(2)) < 1:
        raise ValueError(f"Invalid rate limit {spec!r}: use '<requests>/<seconds>', e.g. '10/300'")
    return RateRule(int(match.group(1)), int(match.group(2)))


def origin_of(url: str) -> str:
    """'https://App.example.com:443/path' -> 'https://app.example.com' (scheme + host + non-default port)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"{url!r} is not an absolute http(s) URL")
    default_port = {"http": 80, "https": 443}[parts.scheme]
    host = parts.hostname.lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port and parts.port != default_port else ""
    return f"{parts.scheme}://{host}{port}"


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
    # Where users reach the web app (scheme://host[:port]). Trusted origin for CSRF checks and the base of
    # password-reset links — never derived from the request's Host / X-Forwarded-Host headers.
    app_public_url: str = "http://localhost:3000"
    # Browser origins allowed to call the API directly (cross-origin, with cookies). Not needed with the
    # default same-origin Next.js proxy. NoDecode: accept "a,b" instead of requiring a JSON array.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Extra origins whose state-changing requests are accepted (APP_PUBLIC_URL and CORS_ORIGINS always are).
    csrf_trusted_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Peers whose X-Forwarded-For header is believed (IPs or CIDRs). Requests carrying a valid APP_API_TOKEN
    # come from the Next.js proxy and are trusted too. Everyone else is identified by the socket address.
    trusted_proxy_ips: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["127.0.0.1", "::1"])
    # Shared secret between the Next.js server-side proxy and this API (required in production). When set,
    # every /api route except /api/health requires "Authorization: Bearer <token>". It authenticates the
    # proxy, not users: user sessions travel separately in a cookie.
    app_api_token: SecretStr | None = None

    # --- Accounts & sessions ---------------------------------------------------
    registration_enabled: bool = True
    # NIST SP 800-63B-style policy: length over composition rules, no truncation, any Unicode allowed.
    # 8 is NIST's floor; it recommends 15 when the password is the only sign-in factor (as it is here).
    password_min_length: int = 8
    password_max_length: int = 128
    session_cookie_name: str = "aica_session"
    csrf_cookie_name: str = "aica_csrf"
    # Must be true behind HTTPS (enforced in production). With the "__Host-" name prefix browsers also
    # guarantee the cookie is host-only, Secure and Path=/.
    session_cookie_secure: bool = False
    session_cookie_samesite: Literal["lax", "strict"] = "lax"
    session_ttl_seconds: int = 12 * 3600  # absolute lifetime of a normal sign-in
    session_remember_ttl_seconds: int = 30 * 86400  # absolute lifetime with "Remember me"
    session_idle_timeout_seconds: int = 7 * 86400  # sign out after this long without any request
    password_reset_ttl_seconds: int = 30 * 60

    # --- Mail (password reset) -------------------------------------------------
    # smtp: real delivery · outbox: write .eml files to MAIL_OUTBOX_DIR (development only) ·
    # memory: keep messages in process (tests only) · disabled: password reset is switched off (503).
    mail_backend: Literal["smtp", "outbox", "memory", "disabled"] = "outbox"
    mail_outbox_dir: Path = BACKEND_DIR / "data" / "outbox"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = 15.0

    # --- Rate limits ("<requests>/<seconds>", fixed windows stored in the database) ---------------------
    rate_limit_enabled: bool = True
    rate_limit_login_ip: str = "20/300"
    rate_limit_login_account: str = "10/900"  # failed sign-ins per normalised email
    rate_limit_register_ip: str = "10/3600"
    rate_limit_forgot_ip: str = "10/3600"
    rate_limit_forgot_account: str = "3/3600"
    rate_limit_reset_ip: str = "20/3600"

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

    @field_validator("cors_origins", "csrf_trusted_origins", "trusted_proxy_ips", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "anthropic_api_key",
        "anthropic_effort",
        "openai_api_key",
        "openai_base_url",
        "openai_model",
        "app_api_token",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "smtp_from",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_security(self) -> Self:
        """Refuse configurations that would silently weaken authentication."""
        self.app_public_url = self.app_public_url.rstrip("/")
        origin_of(self.app_public_url)  # raises for relative or non-http(s) URLs
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS cannot contain '*': the API is called with cookies (credentials).")
        for origin in [*self.cors_origins, *self.csrf_trusted_origins]:
            origin_of(origin)
        for name in ("login_ip", "login_account", "register_ip", "forgot_ip", "forgot_account", "reset_ip"):
            parse_rate(getattr(self, f"rate_limit_{name}"))
        if not 1 <= self.password_min_length <= self.password_max_length or self.password_max_length < 64:
            raise ValueError("Need 1 <= PASSWORD_MIN_LENGTH <= PASSWORD_MAX_LENGTH and PASSWORD_MAX_LENGTH >= 64.")
        if min(self.session_ttl_seconds, self.session_idle_timeout_seconds, self.password_reset_ttl_seconds) < 60:
            raise ValueError("Session, idle and reset-token lifetimes must be at least 60 seconds.")
        if self.session_remember_ttl_seconds < self.session_ttl_seconds:
            raise ValueError("SESSION_REMEMBER_TTL_SECONDS must be >= SESSION_TTL_SECONDS.")
        for cookie in (self.session_cookie_name, self.csrf_cookie_name):
            if cookie.startswith("__Host-") and not self.session_cookie_secure:
                raise ValueError(
                    f"Cookie {cookie!r} uses the __Host- prefix, which requires SESSION_COOKIE_SECURE=true."
                )
        if self.smtp_ssl and self.smtp_starttls:
            raise ValueError("Set either SMTP_SSL (implicit TLS, usually port 465) or SMTP_STARTTLS, not both.")
        if self.mail_backend == "smtp" and not (self.smtp_host and self.smtp_from):
            raise ValueError("MAIL_BACKEND=smtp requires SMTP_HOST and SMTP_FROM.")

        if self.app_env == "production":
            problems = []
            if not self.app_public_url.startswith("https://"):
                problems.append("APP_PUBLIC_URL must be an https:// URL")
            if not self.session_cookie_secure:
                problems.append("SESSION_COOKIE_SECURE must be true (cookies would travel over plain HTTP)")
            token = self.app_api_token.get_secret_value() if self.app_api_token else ""
            if len(token) < 32:
                problems.append("APP_API_TOKEN must be a random value of at least 32 characters")
            if self.mail_backend in {"outbox", "memory"}:
                problems.append(
                    f"MAIL_BACKEND={self.mail_backend} is for development/tests; use smtp (or disabled to switch "
                    "password reset off)"
                )
            if problems:
                raise ValueError("Unsafe production configuration:\n  - " + "\n  - ".join(problems))
        return self

    @property
    def public_origin(self) -> str:
        return origin_of(self.app_public_url)

    @property
    def trusted_origins(self) -> frozenset[str]:
        """Origins whose cookie-authenticated, state-changing requests are accepted."""
        return frozenset(origin_of(o) for o in [self.app_public_url, *self.cors_origins, *self.csrf_trusted_origins])

    def rate_rule(self, name: str) -> RateRule:
        return parse_rate(getattr(self, f"rate_limit_{name}"))

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
