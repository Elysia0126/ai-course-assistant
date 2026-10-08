"""Forgot/reset password: uniform responses, single-use expiring tokens, session revocation, real SMTP."""

import hashlib
import logging
import re
import threading
from datetime import timedelta
from email import message_from_bytes
from email.message import Message

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.config import Settings
from app.db.types import utcnow
from app.models import AuthSession, PasswordResetToken, User
from app.services import auth as auth_service
from app.services.auth import InvalidResetTokenError
from app.services.mailer import EmailMessage, OutboxMailer, SMTPMailer, password_reset_email
from tests.conftest import STUDENT
from tests.helpers import PASSWORD, SESSION_COOKIE, csrf, login, set_cookie

NEW_PASSWORD = "an entirely new passphrase"
_LINK = re.compile(r"http://testserver/reset-password#token=([A-Za-z0-9_-]+)")


def _request_reset(c: TestClient, email: str):
    csrf(c)
    return c.post("/api/auth/forgot-password", json={"email": email})


def _token_from_mail(app) -> str:
    message = app.state.mailer.messages[-1]
    match = _LINK.search(message.text)
    assert match, message.text
    return match.group(1)


def _reset(c: TestClient, token: str, password: str = NEW_PASSWORD):
    csrf(c)
    return c.post("/api/auth/reset-password", json={"token": token, "password": password, "password_confirm": password})


def test_reset_flow_end_to_end(client: TestClient, make_client, app) -> None:
    old_session = client.cookies.get(SESSION_COOKIE)
    other_device = make_client()
    assert login(other_device, STUDENT).status_code == 200

    stranger = make_client()
    response = _request_reset(stranger, "  Student@Example.com ")
    assert response.status_code == 202
    mail = app.state.mailer.messages[-1]
    assert mail.to == STUDENT and "Reset your" in mail.subject
    assert "expires in 30 minutes" in mail.text and mail.html and "reset-password#token=" in mail.html
    token = _token_from_mail(app)
    assert token not in response.text  # the link only goes out by email

    with app.state.session_factory() as db:
        stored = db.scalar(select(PasswordResetToken))
        assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest() != token

    done = _reset(stranger, token)
    assert done.status_code == 200, done.text
    assert SESSION_COOKIE not in stranger.cookies  # no automatic sign-in after a reset

    # Every existing session of that user is gone, on every device.
    assert client.get("/api/courses").status_code == 401
    assert other_device.get("/api/courses").status_code == 401
    with app.state.session_factory() as db:
        sessions = db.scalars(select(AuthSession).join(User).where(User.email == STUDENT)).all()
        assert sessions and all(s.revoked_at is not None for s in sessions)
    replay = make_client()
    set_cookie(replay, SESSION_COOKIE, old_session)
    assert replay.get("/api/auth/me").status_code == 401

    assert login(stranger, STUDENT, PASSWORD).status_code == 401
    assert login(stranger, STUDENT, NEW_PASSWORD).status_code == 200
    assert _reset(make_client(), token, "yet another long passphrase").status_code == 400  # single use


def test_unknown_and_known_emails_get_the_same_answer(client: TestClient, make_client, app) -> None:
    known = _request_reset(make_client(), STUDENT)
    sent = len(app.state.mailer.messages)
    unknown = _request_reset(make_client(), "nobody@example.com")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(app.state.mailer.messages) == sent  # nothing is sent for unknown addresses


def test_disabled_accounts_get_no_reset_mail(client: TestClient, make_client, app) -> None:
    with app.state.session_factory() as db:
        db.execute(update(User).where(User.email == STUDENT).values(is_active=False))
        db.commit()
    assert _request_reset(make_client(), STUDENT).status_code == 202
    assert app.state.mailer.messages == []


def test_expired_reused_superseded_and_forged_tokens_fail(client: TestClient, make_client, app) -> None:
    c = make_client()
    _request_reset(c, STUDENT)
    first = _token_from_mail(app)
    _request_reset(c, STUDENT)
    second = _token_from_mail(app)
    assert first != second
    superseded = _reset(c, first)
    assert superseded.status_code == 400 and superseded.json()["error"]["code"] == "invalid_reset_token"

    with app.state.session_factory() as db:
        db.execute(update(PasswordResetToken).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert _reset(c, second).status_code == 400  # expired

    assert _reset(c, "x" * 43).status_code == 400  # never issued
    assert login(c, STUDENT, PASSWORD).status_code == 200  # nothing changed


def test_reset_enforces_the_password_policy(client: TestClient, make_client, app) -> None:
    c = make_client()
    _request_reset(c, STUDENT)
    token = _token_from_mail(app)
    csrf(c)
    weak = c.post("/api/auth/reset-password", json={"token": token, "password": "short", "password_confirm": "short"})
    assert weak.status_code == 422 and weak.json()["error"]["details"][0]["field"] == "password"
    mismatch = c.post(
        "/api/auth/reset-password", json={"token": token, "password": NEW_PASSWORD, "password_confirm": "other"}
    )
    assert mismatch.status_code == 422
    assert _reset(c, token).status_code == 200  # the token survived the failed attempts


def test_concurrent_resets_with_one_token_succeed_once(client: TestClient, app, settings) -> None:
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == STUDENT))
        token = auth_service.create_reset_token(db, settings, user)
        db.commit()

    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def attempt(n: int) -> None:
        with app.state.session_factory() as db:
            barrier.wait()
            try:
                auth_service.reset_password(
                    db, settings, token, f"parallel passphrase {n}!", f"parallel passphrase {n}!"
                )
                outcomes.append("ok")
            except InvalidResetTokenError:
                outcomes.append("rejected")

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok", "rejected", "rejected", "rejected"]


def test_password_reset_can_be_switched_off(anon_client: TestClient, settings, monkeypatch) -> None:
    monkeypatch.setattr(settings, "mail_backend", "disabled")
    response = _request_reset(anon_client, STUDENT)
    assert response.status_code == 503 and response.json()["error"]["code"] == "password_reset_unavailable"


def test_secrets_never_reach_the_logs(anon_client: TestClient, app, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    from tests.helpers import register

    register(anon_client, "logs@example.com")
    session_token = anon_client.cookies.get(SESSION_COOKIE)
    anon_client.post("/api/auth/logout")
    login(anon_client, "logs@example.com", "a wrong password for the logs")
    _request_reset(anon_client, "logs@example.com")
    reset_token = _token_from_mail(app)
    _reset(anon_client, reset_token)
    for secret in (PASSWORD, NEW_PASSWORD, session_token, reset_token):
        assert secret not in caplog.text


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _smtp_server(port: int):
    from aiosmtpd.controller import Controller

    class Collector:
        def __init__(self) -> None:
            self.messages: list[Message] = []

        async def handle_DATA(self, server, session, envelope):
            self.messages.append(message_from_bytes(envelope.content))
            return "250 OK"

    handler = Collector()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    return controller, handler


def test_smtp_mailer_delivers_to_a_real_smtp_server() -> None:
    port = _free_port()
    controller, inbox = _smtp_server(port)
    try:
        settings = Settings(
            _env_file=None,
            mail_backend="smtp",
            smtp_host="127.0.0.1",
            smtp_port=port,
            smtp_starttls=False,
            smtp_from="AI Course Assistant <no-reply@example.com>",
            app_public_url="https://study.example.com",
        )
        SMTPMailer(settings).send(password_reset_email(settings, "ada@example.com", "tok" * 15))
    finally:
        controller.stop()
    [message] = inbox.messages
    assert message["To"] == "ada@example.com" and message["From"].endswith("<no-reply@example.com>")
    plain = next(part for part in message.walk() if part.get_content_type() == "text/plain")
    assert "https://study.example.com/reset-password#token=" + "tok" * 15 in plain.get_payload(decode=True).decode()


def test_outbox_mailer_writes_eml_files(tmp_path) -> None:
    settings = Settings(_env_file=None, mail_backend="outbox", mail_outbox_dir=tmp_path)
    OutboxMailer(settings).send(EmailMessage(to="ada@example.com", subject="Hello", text="Body"))
    [path] = list(tmp_path.glob("*.eml"))
    assert message_from_bytes(path.read_bytes())["Subject"] == "Hello"
