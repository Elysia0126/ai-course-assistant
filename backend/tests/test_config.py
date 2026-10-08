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


def test_service_token_guards_the_api_and_is_not_a_user_login(settings) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    secured = settings.model_copy(update={"app_api_token": SecretStr("s3cret")})
    with TestClient(create_app(secured)) as client:
        assert client.get("/api/health").status_code == 200
        denied = client.get("/api/courses")
        assert denied.status_code == 401 and denied.json()["error"]["code"] == "service_token_invalid"
        assert client.get("/api/courses", headers={"Authorization": "Bearer wrong"}).status_code == 401
        # The proxy's token proves where a request came from, not who the user is.
        anonymous = client.get("/api/courses", headers={"Authorization": "Bearer s3cret"})
        assert anonymous.status_code == 401 and anonymous.json()["error"]["code"] == "authentication_required"


SAFE_PRODUCTION = {
    "app_env": "production",
    "app_public_url": "https://study.example.com",
    "session_cookie_secure": True,
    "app_api_token": "x" * 40,
    "mail_backend": "smtp",
    "smtp_host": "smtp.example.com",
    "smtp_from": "AI Course Assistant <no-reply@example.com>",
}


def test_production_settings_accept_a_safe_configuration() -> None:
    settings = Settings(_env_file=None, **SAFE_PRODUCTION)
    assert settings.public_origin == "https://study.example.com"
    assert settings.trusted_origins == {"https://study.example.com"}


@pytest.mark.parametrize(
    ("override", "complaint"),
    [
        ({"app_public_url": "http://study.example.com"}, "APP_PUBLIC_URL must be an https"),
        ({"session_cookie_secure": False}, "SESSION_COOKIE_SECURE must be true"),
        ({"app_api_token": None}, "APP_API_TOKEN must be a random value"),
        ({"app_api_token": "short"}, "APP_API_TOKEN must be a random value"),
        ({"mail_backend": "outbox"}, "MAIL_BACKEND=outbox is for development"),
    ],
)
def test_production_settings_refuse_unsafe_values(override: dict, complaint: str) -> None:
    with pytest.raises(ValueError, match=complaint):
        Settings(_env_file=None, **{**SAFE_PRODUCTION, **override})


@pytest.mark.parametrize(
    ("values", "complaint"),
    [
        ({"cors_origins": ["*"]}, "cannot contain"),
        ({"session_cookie_name": "__Host-aica_session"}, "requires SESSION_COOKIE_SECURE"),
        ({"mail_backend": "smtp"}, "requires SMTP_HOST and SMTP_FROM"),
        ({"rate_limit_login_ip": "lots"}, "Invalid rate limit"),
        ({"app_public_url": "/relative"}, "not an absolute"),
        ({"password_min_length": 8, "password_max_length": 32}, "PASSWORD_MAX_LENGTH >= 64"),
        ({"smtp_ssl": True, "smtp_starttls": True}, "not both"),
    ],
)
def test_settings_reject_insecure_or_broken_values(values: dict, complaint: str) -> None:
    with pytest.raises(ValueError, match=complaint):
        Settings(_env_file=None, **values)


def test_public_url_and_origin_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "https://Admin.Example.com:443, http://localhost:3001")
    settings = Settings(_env_file=None, app_public_url="http://localhost:3000/")
    assert settings.app_public_url == "http://localhost:3000"
    assert settings.trusted_origins == {
        "http://localhost:3000",
        "https://admin.example.com",
        "http://localhost:3001",
    }


def test_documented_env_example_is_a_valid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import BACKEND_DIR

    for name in ("APP_ENV", "APP_PUBLIC_URL", "MAIL_BACKEND", "APP_API_TOKEN", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)  # let the file speak, not the test environment
    settings = Settings(_env_file=BACKEND_DIR.parent / ".env.example")
    assert settings.app_env == "development" and settings.mail_backend == "outbox"
    assert settings.cors_origins == [] and settings.trusted_proxy_ips == ["127.0.0.1", "::1"]
    assert settings.rate_rule("login_account").limit == 10


def test_dialect_helpers() -> None:
    assert Settings(_env_file=None, database_url="postgresql+psycopg://u@h/db").is_postgres
    assert not Settings(_env_file=None, database_url="sqlite:///x.db").is_postgres
    assert Settings(_env_file=None, max_upload_mb=2).max_upload_bytes == 2 * 1024 * 1024
