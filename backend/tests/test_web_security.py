"""CSRF + origin checks, rate limits (with trusted proxies), CORS and private cache headers."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app
from tests.conftest import STUDENT
from tests.helpers import PASSWORD, csrf, login, register


def raw_client(browser: TestClient) -> TestClient:
    """Same cookies as ``browser`` but none of its automatic Origin/CSRF headers."""
    return TestClient(browser.app, cookies=browser.cookies)


def test_state_changing_requests_need_the_csrf_token(client: TestClient) -> None:
    missing = client.post("/api/courses", json={"name": "x"}, headers={"x-csrf-token": ""})
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "csrf_failed"
    wrong = client.post("/api/courses", json={"name": "x"}, headers={"x-csrf-token": "forged-token-value"})
    assert wrong.status_code == 403
    assert client.post("/api/courses", json={"name": "x"}).status_code == 201
    assert client.get("/api/courses").status_code == 200  # safe methods never need it


def test_csrf_token_of_another_session_is_rejected(client: TestClient, make_client) -> None:
    other = make_client("other@example.com")
    foreign_token = csrf(other)
    response = client.post("/api/courses", json={"name": "x"}, headers={"x-csrf-token": foreign_token})
    assert response.status_code == 403

    stale = csrf(client)
    login(client, STUDENT)  # new session → new token
    assert client.post("/api/courses", json={"name": "x"}, headers={"x-csrf-token": stale}).status_code == 403


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"origin": "https://evil.example"}, "origin_not_allowed"),
        ({"origin": "http://testserver.evil.example"}, "origin_not_allowed"),
        ({"origin": "https://testserver"}, "origin_not_allowed"),  # scheme matters
        ({"origin": "http://testserver:8080"}, "origin_not_allowed"),  # port matters
        ({"origin": "null"}, "origin_required"),
        ({}, "origin_required"),
        ({"referer": "https://evil.example/page"}, "origin_not_allowed"),
    ],
)
def test_untrusted_or_missing_origins_are_refused(client: TestClient, headers: dict, code: str) -> None:
    token = csrf(client)
    response = raw_client(client).post("/api/courses", json={"name": "x"}, headers={"x-csrf-token": token, **headers})
    assert response.status_code == 403 and response.json()["error"]["code"] == code


def test_referer_is_accepted_when_origin_is_absent(client: TestClient) -> None:
    token = csrf(client)
    response = raw_client(client).post(
        "/api/courses", json={"name": "x"}, headers={"x-csrf-token": token, "referer": "http://testserver/courses/1"}
    )
    assert response.status_code == 201


def test_login_csrf_needs_the_double_submit_cookie(anon_client: TestClient) -> None:
    register(anon_client, "login-csrf@example.com")
    anon_client.post("/api/auth/logout")  # clears both cookies
    attacker = raw_client(anon_client).post(
        "/api/auth/login",
        json={"email": "login-csrf@example.com", "password": PASSWORD},
        headers={"origin": "http://testserver", "x-csrf-token": "guessed-token-value-0000000000000000"},
    )
    assert attacker.status_code == 403
    assert login(anon_client, "login-csrf@example.com").status_code == 200


def test_login_is_rate_limited_per_account(anon_client: TestClient, settings, monkeypatch) -> None:
    register(anon_client, "target@example.com")
    anon_client.post("/api/auth/logout")
    monkeypatch.setattr(settings, "rate_limit_login_account", "3/900")
    for _ in range(3):
        assert login(anon_client, "target@example.com", "wrong but long enough").status_code == 401
    blocked = login(anon_client, "TARGET@example.com", PASSWORD)  # even the right password, any spelling
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"
    assert 0 < int(blocked.headers["retry-after"]) <= 900


def test_login_is_rate_limited_per_address(anon_client: TestClient, settings, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_login_ip", "2/300")
    statuses = [login(anon_client, f"user{i}@example.com", "wrong but long enough").status_code for i in range(3)]
    assert statuses == [401, 401, 429]


def test_successful_login_resets_the_account_counter(anon_client: TestClient, settings, monkeypatch) -> None:
    register(anon_client, "forgetful@example.com")
    anon_client.post("/api/auth/logout")
    monkeypatch.setattr(settings, "rate_limit_login_account", "3/900")
    for _ in range(2):
        login(anon_client, "forgetful@example.com", "wrong but long enough")
    assert login(anon_client, "forgetful@example.com").status_code == 200
    anon_client.post("/api/auth/logout")
    for _ in range(2):
        assert login(anon_client, "forgetful@example.com", "wrong but long enough").status_code == 401


def test_registration_and_reset_requests_are_rate_limited(anon_client: TestClient, settings, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_forgot_account", "1/3600")
    csrf(anon_client)
    first = anon_client.post("/api/auth/forgot-password", json={"email": "someone@example.com"})
    second = anon_client.post("/api/auth/forgot-password", json={"email": "Someone@Example.com"})
    assert (first.status_code, second.status_code) == (202, 429)

    monkeypatch.setattr(settings, "rate_limit_register_ip", "1/3600")
    register(anon_client, "one@example.com")
    csrf(anon_client)
    another = anon_client.post(
        "/api/auth/register", json={"email": "two@example.com", "password": PASSWORD, "password_confirm": PASSWORD}
    )
    assert another.status_code == 429


@pytest.mark.usefixtures("anon_client")  # migrated schema + clean tables afterwards
def test_forwarded_for_is_only_believed_from_the_trusted_proxy(settings) -> None:
    proxied = settings.model_copy(
        update={"app_api_token": SecretStr("proxy-secret"), "rate_limit_register_ip": "1/3600"}
    )
    app = create_app(proxied)

    def attempt(xff: str, token: str | None) -> int:
        browser = TestClient(app)
        headers = {"origin": "http://testserver", "x-forwarded-for": xff}
        if token:
            headers["authorization"] = f"Bearer {token}"
        csrf_token = browser.get("/api/auth/csrf", headers=headers).json().get("csrf_token", "")
        payload = {"email": f"{xff.replace(',', '').replace(' ', '')}@example.com", "password": PASSWORD}
        payload["password_confirm"] = PASSWORD
        return browser.post(
            "/api/auth/register", json=payload, headers={**headers, "x-csrf-token": csrf_token}
        ).status_code

    try:
        # Through the proxy (valid service token): each client address has its own bucket.
        assert attempt("203.0.113.1", "proxy-secret") == 201
        assert attempt("203.0.113.2", "proxy-secret") == 201
        assert attempt("203.0.113.1", "proxy-secret") == 429
        # Only the right-most hop counts: a client can't prepend fake addresses to escape its bucket.
        assert attempt("198.51.100.9, 203.0.113.2", "proxy-secret") == 429
    finally:
        app.state.engine.dispose()


def test_spoofed_forwarded_for_from_an_untrusted_peer_is_ignored(
    anon_client: TestClient, settings, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_register_ip", "1/3600")
    register(anon_client, "first-spoof@example.com")
    csrf(anon_client)
    spoofed = anon_client.post(
        "/api/auth/register",
        json={"email": "second-spoof@example.com", "password": PASSWORD, "password_confirm": PASSWORD},
        headers={"x-forwarded-for": "192.0.2.77"},
    )
    assert spoofed.status_code == 429  # still counted against the real peer address


def test_cors_allows_only_configured_origins_with_credentials(settings) -> None:
    configured = settings.model_copy(update={"cors_origins": ["https://app.example.com"], "auto_migrate": False})
    app = create_app(configured)
    try:
        browser = TestClient(app)
        preflight = {
            "origin": "https://app.example.com",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type,x-csrf-token",
        }
        allowed = browser.options("/api/courses", headers=preflight)
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
        assert allowed.headers["access-control-allow-credentials"] == "true"
        denied = browser.options("/api/courses", headers={**preflight, "origin": "https://evil.example"})
        assert "access-control-allow-origin" not in denied.headers
    finally:
        app.state.engine.dispose()


def test_private_responses_are_never_cached(client: TestClient, ready_course: dict) -> None:
    cid = ready_course["id"]
    assert client.get("/api/courses").headers["cache-control"] == "no-store"
    assert client.get("/api/auth/me").headers["cache-control"] == "no-store"
    document = client.get(f"/api/courses/{cid}/documents").json()[0]
    assert client.get(f"/api/documents/{document['id']}/file").headers["cache-control"] == "private, no-store"
    stream = client.post(f"/api/courses/{cid}/chat/stream", json={"question": "What is dropout?"})
    assert stream.headers["cache-control"] == "no-store, no-transform"
    anonymous = TestClient(client.app).get("/api/courses")
    assert anonymous.status_code == 401 and anonymous.headers["cache-control"] == "no-store"
