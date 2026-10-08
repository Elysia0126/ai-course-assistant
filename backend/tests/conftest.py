"""Test fixtures.

Tests run hermetically: SQLite + hash embeddings + the offline generator. Set TEST_DATABASE_URL to a
PostgreSQL URL (with pgvector) to run the same suite against the production code paths.

Authentication is never mocked: ``client`` registers a real account through the API and keeps its session
cookie; requests carry Origin + X-CSRF-Token exactly like the web app (see tests/helpers.py).
"""

import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

# Must be set before any app module reads settings.
_TMP = Path(tempfile.mkdtemp(prefix="aca-tests-"))
os.environ.update(
    {
        "APP_ENV": "test",
        "APP_PUBLIC_URL": "http://testserver",
        "MAIL_BACKEND": "memory",
        "LLM_PROVIDER": "offline",
        "EMBEDDING_PROVIDER": "hash",
        "EMBEDDING_DIM": "384",
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{(_TMP / 'test.db').as_posix()}"),
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "LOG_LEVEL": "WARNING",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
        "APP_API_TOKEN": "",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from tests import factories  # noqa: E402
from tests.helpers import browserlike, register  # noqa: E402

STUDENT = "student@example.com"


@pytest.fixture(scope="session")
def settings() -> Settings:
    # Ignore any developer .env so the suite is reproducible.
    return Settings(_env_file=None)


@pytest.fixture(scope="session")
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture()
def anon_client(app) -> Iterator[TestClient]:
    """A browser with no account (yet)."""
    with TestClient(app) as test_client:
        yield browserlike(test_client)
    # Clean slate between tests, keeping the migrated schema.
    with app.state.engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {table.name}"))
    app.state.mailer.messages.clear()


@pytest.fixture()
def client(anon_client: TestClient) -> TestClient:
    """A browser signed in as a freshly registered student."""
    register(anon_client, STUDENT, display_name="Student")
    return anon_client


@pytest.fixture()
def make_client(app, anon_client: TestClient) -> Iterator[Callable[..., TestClient]]:
    """More independent browsers (separate cookie jars), optionally registered as ``email``."""
    clients: list[TestClient] = []

    def factory(email: str | None = None) -> TestClient:
        other = browserlike(TestClient(app))
        clients.append(other)
        if email:
            register(other, email)
        return other

    yield factory
    for other in clients:
        other.close()


@pytest.fixture()
def course(client: TestClient) -> dict:
    response = client.post("/api/courses", json={"name": "Machine Learning Foundations", "code": "ML101"})
    assert response.status_code == 201, response.text
    return response.json()


def upload(client: TestClient, course_id: str, *files: tuple[str, bytes, str]):
    return client.post(
        f"/api/courses/{course_id}/documents",
        files=[("files", (name, data, mime)) for name, data, mime in files],
    )


@pytest.fixture()
def ready_course(client: TestClient, course: dict) -> dict:
    """A course with a PDF, a slide deck and Markdown notes, fully indexed."""
    response = upload(
        client,
        course["id"],
        ("Lecture03_Gradient_Descent.pdf", factories.make_pdf(), "application/pdf"),
        ("Lecture05_Neural_Networks.pptx", factories.make_pptx(), "application/octet-stream"),
        ("Regularization.md", factories.MARKDOWN, "text/markdown"),
    )
    assert response.status_code == 201, response.text
    documents = client.get(f"/api/courses/{course['id']}/documents").json()
    assert {d["status"] for d in documents} == {"ready"}, documents
    return course
