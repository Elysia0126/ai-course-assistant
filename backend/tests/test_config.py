import pytest
from pydantic import SecretStr

from app.core.config import Settings


def test_cors_origins_accept_comma_separated_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, http://localhost:3001")
    assert Settings(_env_file=None).cors_origins == ["http://localhost:3000", "http://localhost:3001"]
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    assert Settings(_env_file=None).cors_origins == ["https://app.example.com"]


def test_blank_optional_values_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    monkeypatch.setenv("ANTHROPIC_EFFORT", "")
    settings = Settings(_env_file=None, llm_provider="auto", openai_api_key=None)
    assert settings.anthropic_api_key is None
    assert settings.anthropic_effort is None
    assert settings.resolved_llm_provider == "offline"


def test_optional_api_token_protects_everything_but_health(settings) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    secured = settings.model_copy(update={"app_api_token": SecretStr("s3cret"), "auto_migrate": False})
    with TestClient(create_app(secured)) as client:
        assert client.get("/api/health").status_code == 200
        denied = client.get("/api/courses")
        assert denied.status_code == 401 and denied.json()["error"]["code"] == "unauthorized"
        assert client.get("/api/courses", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/api/courses", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_dialect_helpers() -> None:
    assert Settings(_env_file=None, database_url="postgresql+psycopg://u@h/db").is_postgres
    assert not Settings(_env_file=None, database_url="sqlite:///x.db").is_postgres
    assert Settings(_env_file=None, max_upload_mb=2).max_upload_bytes == 2 * 1024 * 1024
