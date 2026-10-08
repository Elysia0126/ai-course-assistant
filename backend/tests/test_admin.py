"""Roles, the admin API, the management CLI and isolation of courses created before accounts existed."""

import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app.cli import main as cli
from app.db.types import new_id, utcnow
from app.models import AuthSession, Course, PasswordResetToken, RateLimitCounter, User
from tests.conftest import STUDENT
from tests.helpers import PASSWORD, login

ADMIN = "admin@example.com"


def run_cli(settings, *argv: str, stdin: str | None = None, monkeypatch=None) -> int:
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return cli(list(argv), settings)


@pytest.fixture()
def admin_client(anon_client: TestClient, make_client, settings, monkeypatch) -> TestClient:
    assert (
        run_cli(
            settings,
            "create-user",
            "--email",
            ADMIN,
            "--admin",
            "--password-stdin",
            stdin=PASSWORD + "\n",
            monkeypatch=monkeypatch,
        )
        == 0
    )
    admin = make_client()
    assert login(admin, ADMIN).status_code == 200
    return admin


def insert_legacy_course(engine: Engine, name: str = "Legacy course") -> str:
    """A course row from before accounts existed (owner_id NULL), bypassing today's guards."""
    course_id = new_id()
    now = utcnow()
    with engine.begin() as conn:
        postgres = conn.dialect.name == "postgresql"
        if postgres:  # recreate the pre-0003 situation: the NOT VALID check only guards rows written after it
            conn.execute(text("ALTER TABLE courses DROP CONSTRAINT ck_courses_owner_required"))
        conn.execute(
            text(
                "INSERT INTO courses (id, name, color, created_at, updated_at) "
                "VALUES (:id, :name, 'indigo', :now, :now)"
            ),
            {"id": course_id, "name": name, "now": now},
        )
        if postgres:
            conn.execute(
                text(
                    "ALTER TABLE courses ADD CONSTRAINT ck_courses_owner_required "
                    "CHECK (owner_id IS NOT NULL) NOT VALID"
                )
            )
    return course_id


def test_admin_api_requires_the_admin_role(client: TestClient, admin_client: TestClient, make_client) -> None:
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/users").json()["error"]["code"] == "forbidden"
    assert make_client().get("/api/admin/users").status_code == 401
    users = admin_client.get("/api/admin/users").json()
    assert {u["email"] for u in users} == {STUDENT, ADMIN}
    assert all("password_hash" not in u for u in users)


def test_admins_still_only_see_their_own_courses(client: TestClient, admin_client: TestClient) -> None:
    course = client.post("/api/courses", json={"name": "Private"}).json()
    assert admin_client.get("/api/courses").json() == []
    assert admin_client.get(f"/api/courses/{course['id']}").status_code == 404
    student = next(u for u in admin_client.get("/api/admin/users").json() if u["email"] == STUDENT)
    assert student["course_count"] == 1  # metadata only


def test_disabling_a_user_revokes_sessions_and_blocks_login(client: TestClient, admin_client: TestClient) -> None:
    student = next(u for u in admin_client.get("/api/admin/users").json() if u["email"] == STUDENT)
    disabled = admin_client.patch(f"/api/admin/users/{student['id']}", json={"is_active": False})
    assert disabled.status_code == 200 and disabled.json()["is_active"] is False
    assert client.get("/api/courses").status_code == 401
    assert login(client, STUDENT).json()["error"]["code"] == "account_disabled"

    admin_client.patch(f"/api/admin/users/{student['id']}", json={"is_active": True})
    assert login(client, STUDENT).status_code == 200


def test_admin_guards(admin_client: TestClient, client: TestClient) -> None:
    me = admin_client.get("/api/auth/me").json()
    own = admin_client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
    assert own.status_code == 409 and own.json()["error"]["code"] == "cannot_disable_self"
    escalate = admin_client.patch(f"/api/admin/users/{me['id']}", json={"is_active": True, "role": "admin"})
    assert escalate.status_code == 422  # roles are not editable over the API
    assert admin_client.patch(f"/api/admin/users/{new_id()}", json={"is_active": False}).status_code == 404


def test_role_changes_apply_immediately_and_the_last_admin_is_protected(
    admin_client: TestClient, settings, capsys, monkeypatch
) -> None:
    assert run_cli(settings, "set-role", "--email", ADMIN, "--role", "user") == 1
    assert "last active administrator" in capsys.readouterr().err
    assert run_cli(settings, "set-active", "--email", ADMIN, "--disable") == 1

    # A password that fails the policy creates nothing.
    argv = ("create-user", "--email", "second-admin@example.com", "--admin", "--password-stdin")
    assert run_cli(settings, *argv, stdin="too short\n", monkeypatch=monkeypatch) == 1
    with admin_client.app.state.session_factory() as db:
        assert db.scalar(select(User).where(User.email == "second-admin@example.com")) is None
        db.add(User(email="second-admin@example.com", password_hash="x", role="admin", is_active=True))
        db.commit()
    assert run_cli(settings, "set-role", "--email", ADMIN, "--role", "user") == 0
    assert admin_client.get("/api/admin/users").status_code == 403  # read from the database on every request


def test_legacy_courses_are_isolated_until_assigned(
    client: TestClient, admin_client: TestClient, app, settings, capsys
) -> None:
    legacy_id = insert_legacy_course(app.state.engine)
    for browser in (client, admin_client):
        assert legacy_id not in {c["id"] for c in browser.get("/api/courses").json()}
        assert browser.get(f"/api/courses/{legacy_id}").status_code == 404

    assert run_cli(settings, "validate-ownership") == 1  # orphans left
    assert run_cli(settings, "list-orphan-courses") == 0
    assert legacy_id in capsys.readouterr().out
    assert run_cli(settings, "assign-course", "--course-id", legacy_id, "--email", STUDENT) == 0
    assert legacy_id in {c["id"] for c in client.get("/api/courses").json()}
    assert run_cli(settings, "assign-course", "--course-id", legacy_id, "--email", ADMIN) == 1  # needs --force
    assert run_cli(settings, "validate-ownership") == 0

    another = insert_legacy_course(app.state.engine, "Another legacy course")
    assert run_cli(settings, "assign-orphans", "--email", STUDENT) == 1  # needs --yes
    assert run_cli(settings, "assign-orphans", "--email", STUDENT, "--yes") == 0
    assert another in {c["id"] for c in client.get("/api/courses").json()}


def test_new_courses_without_owner_are_refused(app) -> None:
    with app.state.session_factory() as db:
        db.add(Course(name="No owner"))
        with pytest.raises(ValueError, match="must have an owner"):
            db.commit()


def test_cleanup_removes_expired_rows(client: TestClient, app, settings) -> None:
    old = utcnow() - timedelta(days=30)
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == STUDENT))
        db.add_all(
            [
                AuthSession(user_id=user.id, token_hash="a" * 64, expires_at=old, created_at=old, last_seen_at=old),
                PasswordResetToken(user_id=user.id, token_hash="b" * 64, expires_at=old, created_at=old),
                RateLimitCounter(key="c" * 64, count=3, expires_at=old),
            ]
        )
        db.commit()
    assert run_cli(settings, "cleanup") == 0
    with app.state.session_factory() as db:
        assert db.get(RateLimitCounter, "c" * 64) is None
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash == "a" * 64)) is None
        assert db.scalar(select(PasswordResetToken)) is None
    assert client.get("/api/auth/me").status_code == 200  # live sessions untouched


def test_cli_lists_users(admin_client: TestClient, settings, capsys) -> None:
    capsys.readouterr()
    assert run_cli(settings, "list-users") == 0
    out = capsys.readouterr().out
    assert ADMIN in out and "admin" in out
