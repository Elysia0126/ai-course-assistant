"""Registration, login, sessions (remember me, idle/absolute expiry, revocation) and logout."""

import hashlib
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.errors import ConflictError
from app.db.types import utcnow
from app.main import create_app
from app.models import AuthSession, Role, User
from app.services import auth as auth_service
from tests.conftest import STUDENT
from tests.helpers import PASSWORD, SESSION_COOKIE, browserlike, csrf, login, register, set_cookie


def _set_cookies(response) -> dict[str, str]:
    return {raw.split("=", 1)[0]: raw for raw in response.headers.get_list("set-cookie")}


def _db(app):
    return app.state.session_factory()


def test_register_signs_in_and_never_exposes_secrets(anon_client: TestClient, app, settings) -> None:
    csrf(anon_client)
    response = anon_client.post(
        "/api/auth/register",
        json={
            "email": "  Ada@Example.COM ",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "display_name": " Ada ",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["display_name"] == "Ada"
    assert body["user"]["role"] == "user"
    assert set(body) == {"user", "csrf_token"}
    assert not {"password", "password_hash", "token", "token_hash"} & set(body["user"])

    cookie = _set_cookies(response)[SESSION_COOKIE]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert f"Max-Age={settings.session_ttl_seconds}" in cookie
    assert "Domain" not in cookie and "Secure" not in cookie  # host-only; Secure is a production setting
    token = anon_client.cookies.get(SESSION_COOKIE)
    assert token not in response.text  # the session secret never appears in a body

    with _db(app) as db:
        user = db.scalar(select(User).where(User.email == "ada@example.com"))
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert session.token_hash == hashlib.sha256(token.encode()).hexdigest() != token

    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "ada@example.com"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "not-an-email"}, "email"),
        ({"password": "fourteen chars", "password_confirm": "fourteen chars"}, "password"),
        ({"password_confirm": PASSWORD + "!"}, "password_confirm"),
        ({"password": "a" * 20, "password_confirm": "a" * 20}, "password"),
        ({"password": "x" * 129, "password_confirm": "x" * 129}, "password"),
        ({"role": "admin"}, "role"),
        ({"is_active": False}, "is_active"),
    ],
)
def test_register_validation(anon_client: TestClient, payload: dict, field: str) -> None:
    csrf(anon_client)
    body = {"email": "new@example.com", "password": PASSWORD, "password_confirm": PASSWORD, **payload}
    response = anon_client.post("/api/auth/register", json=body)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == field
    assert PASSWORD not in response.text  # submitted passwords are never echoed back


def test_password_policy_allows_long_unicode_passphrases_without_trimming(anon_client: TestClient) -> None:
    passphrase = "  我的课程助手 très sûr 🔒  "  # 15+ characters, spaces at both ends
    register(anon_client, "unicode@example.com", passphrase)
    anon_client.post("/api/auth/logout")
    assert login(anon_client, "unicode@example.com", passphrase.strip()).status_code == 401
    assert login(anon_client, "unicode@example.com", passphrase).status_code == 200
    # Exactly the minimum length is fine.
    register(anon_client, "minimum@example.com", "fifteen chars!!")


def test_email_is_case_insensitive_and_unique(anon_client: TestClient, make_client) -> None:
    register(anon_client, "Grace@Example.com")
    other = make_client()
    csrf(other)
    duplicate = other.post(
        "/api/auth/register",
        json={"email": "grace@EXAMPLE.com", "password": PASSWORD, "password_confirm": PASSWORD},
    )
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "email_taken"
    assert login(other, "GRACE@example.com ").status_code == 200


def test_unique_constraint_decides_concurrent_sign_ups(app, settings, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate the race: both requests passed the "is this email free?" check before either inserted.
    monkeypatch.setattr(auth_service, "find_user_by_email", lambda db, email: None)
    with _db(app) as first, _db(app) as second:
        auth_service.create_user(
            first, settings, email="race@example.com", password=PASSWORD, password_confirm=PASSWORD
        )
        first.commit()
        with pytest.raises(ConflictError):
            auth_service.create_user(
                second, settings, email="race@example.com", password=PASSWORD, password_confirm=PASSWORD
            )
    with _db(app) as db:
        assert db.scalar(select(func.count(User.id)).where(User.email == "race@example.com")) == 1
        db.execute(User.__table__.delete().where(User.email == "race@example.com"))
        db.commit()


def test_parallel_registrations_with_the_same_email(anon_client: TestClient, make_client) -> None:
    clients = [anon_client, make_client()]
    for c in clients:
        csrf(c)
    barrier = threading.Barrier(len(clients))
    statuses: list[int] = []

    def sign_up(c: TestClient) -> None:
        barrier.wait()
        response = c.post(
            "/api/auth/register",
            json={"email": "twin@example.com", "password": PASSWORD, "password_confirm": PASSWORD},
        )
        statuses.append(response.status_code)

    threads = [threading.Thread(target=sign_up, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [201, 409]


def test_login_failures_are_indistinguishable(anon_client: TestClient) -> None:
    register(anon_client, "known@example.com")
    anon_client.post("/api/auth/logout")
    wrong_password = login(anon_client, "known@example.com", "definitely the wrong password")
    unknown_email = login(anon_client, "nobody@example.com", "definitely the wrong password")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["error"]["code"] == "invalid_credentials"
    assert SESSION_COOKIE not in _set_cookies(wrong_password)


def test_remember_me_sets_matching_cookie_and_database_lifetimes(anon_client: TestClient, app, settings) -> None:
    register(anon_client, "remember@example.com")
    anon_client.post("/api/auth/logout")
    response = login(anon_client, "remember@example.com", remember=True)
    assert response.status_code == 200
    assert f"Max-Age={settings.session_remember_ttl_seconds}" in _set_cookies(response)[SESSION_COOKIE]
    token = anon_client.cookies.get(SESSION_COOKIE)
    with _db(app) as db:
        session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest())
        )
        lifetime = (session.expires_at - session.created_at).total_seconds()
        assert session.remember and lifetime == pytest.approx(settings.session_remember_ttl_seconds, abs=2)


def test_login_issues_a_fresh_session_and_revokes_the_previous_one(client: TestClient, app) -> None:
    before = client.cookies.get(SESSION_COOKIE)
    response = login(client, STUDENT)
    assert response.status_code == 200
    after = client.cookies.get(SESSION_COOKIE)
    assert after != before
    with _db(app) as db:
        old = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hashlib.sha256(before.encode()).hexdigest())
        )
        assert old.revoked_at is not None


def test_attacker_chosen_cookie_is_never_adopted(anon_client: TestClient) -> None:
    register(anon_client, "victim@example.com")
    anon_client.post("/api/auth/logout")
    planted = "attacker-chosen-session-value-0123456789abcdef"
    set_cookie(anon_client, SESSION_COOKIE, planted)
    assert login(anon_client, "victim@example.com").status_code == 200
    assert anon_client.cookies.get(SESSION_COOKIE) != planted


def test_logout_revokes_the_session_and_old_cookie_replay_fails(client: TestClient, make_client) -> None:
    token = client.cookies.get(SESSION_COOKIE)
    assert client.get("/api/courses").status_code == 200
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    cleared = _set_cookies(response)
    assert "Max-Age=0" in cleared[SESSION_COOKIE] and "Max-Age=0" in cleared["aica_csrf"]
    assert client.get("/api/auth/me").status_code == 401

    replay = make_client()
    set_cookie(replay, SESSION_COOKIE, token)
    denied = replay.get("/api/courses")
    assert denied.status_code == 401 and denied.json()["error"]["code"] == "session_expired"
    assert "Max-Age=0" in _set_cookies(denied)[SESSION_COOKIE]  # the stale cookie is cleared


def test_forged_cookie_is_rejected(anon_client: TestClient) -> None:
    set_cookie(anon_client, SESSION_COOKIE, "forged-token-that-was-never-issued-by-the-server")
    response = anon_client.get("/api/courses")
    assert response.status_code == 401 and response.json()["error"]["code"] == "session_expired"
    fresh = TestClient(anon_client.app)
    assert fresh.get("/api/courses").json()["error"]["code"] == "authentication_required"


def test_idle_timeout_and_absolute_expiry(client: TestClient, app, settings) -> None:
    token_hash = hashlib.sha256(client.cookies.get(SESSION_COOKIE).encode()).hexdigest()
    now = utcnow()

    # Activity slides the idle window (refreshed at most once a minute).
    with _db(app) as db:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == token_hash)
            .values(last_seen_at=now - timedelta(minutes=5))
        )
        db.commit()
    assert client.get("/api/auth/me").status_code == 200
    with _db(app) as db:
        seen = db.scalar(select(AuthSession.last_seen_at).where(AuthSession.token_hash == token_hash))
        assert seen > now - timedelta(minutes=1)

    # Idle for longer than the timeout: signed out (and the session is revoked for good).
    idle = timedelta(seconds=settings.session_idle_timeout_seconds + 1)
    with _db(app) as db:
        db.execute(update(AuthSession).where(AuthSession.token_hash == token_hash).values(last_seen_at=now - idle))
        db.commit()
    assert client.get("/api/auth/me").json()["error"]["code"] == "session_expired"

    # Past the absolute expiry, even when active.
    login(client, STUDENT)
    token_hash = hashlib.sha256(client.cookies.get(SESSION_COOKIE).encode()).hexdigest()
    with _db(app) as db:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == token_hash)
            .values(expires_at=now - timedelta(seconds=1))
        )
        db.commit()
    assert client.get("/api/courses").status_code == 401


def test_disabled_accounts_lose_access_immediately(client: TestClient, app) -> None:
    with _db(app) as db:
        db.execute(update(User).where(User.email == STUDENT).values(is_active=False))
        db.commit()
    assert client.get("/api/courses").status_code == 401
    client.cookies.clear()
    disabled = login(client, STUDENT)
    assert disabled.status_code == 403 and disabled.json()["error"]["code"] == "account_disabled"
    assert login(client, STUDENT, "a wrong password, still long").status_code == 401


def test_sessions_survive_an_api_restart(client: TestClient, settings) -> None:
    token = client.cookies.get(SESSION_COOKIE)
    restarted = create_app(settings.model_copy(update={"auto_migrate": False}))
    with TestClient(restarted) as fresh:
        set_cookie(fresh, SESSION_COOKIE, token)
        assert fresh.get("/api/auth/me").json()["email"] == STUDENT
    restarted.state.engine.dispose()


def test_first_account_is_not_an_admin(anon_client: TestClient, app) -> None:
    register(anon_client, "first@example.com")
    with _db(app) as db:
        assert db.scalar(select(User.role).where(User.email == "first@example.com")) == Role.USER


def test_registration_can_be_closed(anon_client: TestClient, settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "registration_enabled", False)
    csrf(anon_client)
    response = anon_client.post(
        "/api/auth/register", json={"email": "late@example.com", "password": PASSWORD, "password_confirm": PASSWORD}
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "registration_disabled"


def test_csrf_token_is_bound_to_the_session(client: TestClient) -> None:
    first = csrf(client)
    assert csrf(client) == first  # stable across calls/tabs for one session
    login(client, STUDENT)
    assert csrf(client) != first  # a new session has a new token


def test_new_browser_gets_an_anonymous_csrf_token(app) -> None:
    browser = browserlike(TestClient(app))
    token = csrf(browser)
    assert browser.cookies.get("aica_csrf") == token
    assert csrf(browser) == token  # reused while the cookie lives
