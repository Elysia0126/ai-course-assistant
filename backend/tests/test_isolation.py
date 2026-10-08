"""Two independent users: nothing of one is reachable by the other, by any endpoint or nested id."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests import factories
from tests.conftest import upload
from tests.helpers import csrf


@pytest.fixture()
def alice(client: TestClient, ready_course: dict) -> dict:
    """The default student, with one of everything."""
    cid = ready_course["id"]
    documents = client.get(f"/api/courses/{cid}/documents").json()
    pdf = next(d for d in documents if d["file_type"] == "pdf")
    hit = client.post(f"/api/courses/{cid}/search", json={"query": "warmup"}).json()["results"][0]
    chat = client.post(f"/api/courses/{cid}/chat", json={"question": "What is momentum?"}).json()
    quiz = client.post(f"/api/courses/{cid}/quizzes", json={"num_questions": 2, "question_types": ["mcq"]}).json()
    client.post(f"/api/quizzes/{quiz['id']}/attempts", json={"answers": {}})
    deck = client.post(f"/api/courses/{cid}/decks", json={"num_cards": 3}).json()
    return {
        "course": cid,
        "document": pdf["id"],
        "chunk": hit["chunk_id"],
        "session": chat["session_id"],
        "quiz": quiz["id"],
        "questions": [q["id"] for q in quiz["questions"]],
        "deck": deck["id"],
        "card": deck["cards"][0]["id"],
    }


def _endpoints(ids: dict) -> list[tuple[str, str, dict | None]]:
    c, d, ch, s, q, dk, card = (ids[k] for k in ("course", "document", "chunk", "session", "quiz", "deck", "card"))
    return [
        ("GET", f"/api/courses/{c}", None),
        ("PATCH", f"/api/courses/{c}", {"name": "taken over"}),
        ("GET", f"/api/courses/{c}/documents", None),
        ("POST", f"/api/courses/{c}/reindex", None),
        ("GET", f"/api/documents/{d}", None),
        ("GET", f"/api/documents/{d}/file", None),
        ("GET", f"/api/documents/{d}/chunks", None),
        ("POST", f"/api/documents/{d}/reprocess", None),
        ("GET", f"/api/chunks/{ch}", None),
        ("POST", f"/api/courses/{c}/search", {"query": "learning rate"}),
        ("POST", f"/api/courses/{c}/chat", {"question": "What is Adam?"}),
        ("POST", f"/api/courses/{c}/chat/stream", {"question": "What is Adam?"}),
        ("GET", f"/api/courses/{c}/chat/sessions", None),
        ("GET", f"/api/chat/sessions/{s}", None),
        ("GET", f"/api/courses/{c}/quizzes", None),
        ("POST", f"/api/courses/{c}/quizzes", {"num_questions": 2}),
        ("GET", f"/api/quizzes/{q}", None),
        ("POST", f"/api/quizzes/{q}/attempts", {"answers": {}}),
        ("GET", f"/api/quizzes/{q}/attempts", None),
        ("GET", f"/api/courses/{c}/decks", None),
        ("POST", f"/api/courses/{c}/decks", {"num_cards": 2}),
        ("GET", f"/api/decks/{dk}", None),
        ("GET", f"/api/decks/{dk}/study", None),
        ("POST", f"/api/decks/{dk}/reset", None),
        ("POST", f"/api/flashcards/{card}/review", {"rating": "easy"}),
        # Destructive ones last, so a failure above can't be masked by a deletion.
        ("DELETE", f"/api/chat/sessions/{s}", None),
        ("DELETE", f"/api/quizzes/{q}", None),
        ("DELETE", f"/api/decks/{dk}", None),
        ("DELETE", f"/api/documents/{d}", None),
        ("DELETE", f"/api/courses/{c}", None),
    ]


def _snapshot(c: TestClient, ids: dict) -> dict:
    course = c.get(f"/api/courses/{ids['course']}").json()
    deck = c.get(f"/api/decks/{ids['deck']}").json()
    return {
        "name": course["name"],
        "stats": course["stats"],
        "documents": sorted(d["id"] for d in c.get(f"/api/courses/{ids['course']}/documents").json()),
        "sessions": [s["message_count"] for s in c.get(f"/api/courses/{ids['course']}/chat/sessions").json()],
        "attempts": len(c.get(f"/api/quizzes/{ids['quiz']}/attempts").json()),
        "cards": [(card["id"], card["review_count"], card["due_at"]) for card in deck["cards"]],
    }


def test_other_users_get_404_everywhere_and_change_nothing(
    client: TestClient, alice: dict, make_client: Callable[..., TestClient]
) -> None:
    before = _snapshot(client, alice)
    bob = make_client("bob@example.com")
    assert bob.get("/api/courses").json() == []

    for method, path, body in _endpoints(alice):
        response = bob.request(method, path, json=body)
        assert response.status_code == 404, (method, path, response.status_code, response.text)
        assert response.headers["content-type"].startswith("application/json")  # SSE included: no stream starts
        assert response.json()["error"]["code"] == "not_found"

    upload_attempt = upload(bob, alice["course"], ("notes.md", factories.MARKDOWN, "text/markdown"))
    assert upload_attempt.status_code == 404
    assert _snapshot(client, alice) == before


def test_anonymous_requests_get_401_everywhere(client: TestClient, alice: dict, make_client) -> None:
    anonymous = make_client()
    csrf(anonymous)  # a valid (anonymous) CSRF token, so the 401 comes from authentication
    for method, path, body in [*_endpoints(alice), ("GET", "/api/courses", None), ("POST", "/api/demo", None)]:
        response = anonymous.request(method, path, json=body)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json()["error"]["code"] == "authentication_required"


def test_lists_and_stats_only_count_your_own_data(client: TestClient, alice: dict, make_client) -> None:
    bob = make_client("bob@example.com")
    own = bob.post("/api/courses", json={"name": "Bob's course"}).json()
    listed = bob.get("/api/courses").json()
    assert [c["id"] for c in listed] == [own["id"]]
    assert listed[0]["stats"]["document_count"] == 0 and listed[0]["stats"]["quiz_count"] == 0
    assert [c["id"] for c in client.get("/api/courses").json()] == [alice["course"]]


def test_nested_ids_from_other_users_or_courses_are_rejected(client: TestClient, alice: dict, make_client) -> None:
    bob = make_client("bob@example.com")
    course = bob.post("/api/courses", json={"name": "Bob's course"}).json()
    assert upload(bob, course["id"], ("notes.md", factories.MARKDOWN, "text/markdown")).status_code == 201
    cid = course["id"]
    foreign = [alice["document"]]

    for path, body in [
        (f"/api/courses/{cid}/search", {"query": "dropout", "document_ids": foreign}),
        (f"/api/courses/{cid}/chat", {"question": "What is dropout?", "document_ids": foreign}),
        (f"/api/courses/{cid}/chat/stream", {"question": "What is dropout?", "document_ids": foreign}),
        (f"/api/courses/{cid}/chat", {"question": "What is dropout?", "session_id": alice["session"]}),
        (f"/api/courses/{cid}/quizzes", {"num_questions": 2, "document_ids": foreign}),
        (f"/api/courses/{cid}/decks", {"num_cards": 2, "document_ids": foreign}),
    ]:
        response = bob.post(path, json=body)
        assert response.status_code == 404, (path, response.text)

    quiz = bob.post(f"/api/courses/{cid}/quizzes", json={"num_questions": 2, "question_types": ["mcq"]}).json()
    smuggled = bob.post(f"/api/quizzes/{quiz['id']}/attempts", json={"answers": {alice["questions"][0]: "x"}})
    assert smuggled.status_code == 400 and smuggled.json()["error"]["code"] == "invalid_answers"

    # The same holds between two courses of one user.
    second = client.post("/api/courses", json={"name": "Second course"}).json()
    cross = client.post(f"/api/courses/{second['id']}/search", json={"query": "x", "document_ids": [alice["document"]]})
    assert cross.status_code == 404


def test_owner_cannot_be_chosen_or_changed_by_the_client(client: TestClient, alice: dict, make_client) -> None:
    bob = make_client("bob@example.com")
    me = client.get("/api/auth/me").json()
    planted = bob.post("/api/courses", json={"name": "Trojan", "owner_id": me["id"]}).json()
    assert planted["id"] in {c["id"] for c in bob.get("/api/courses").json()}
    assert planted["id"] not in {c["id"] for c in client.get("/api/courses").json()}
    bob.patch(f"/api/courses/{planted['id']}", json={"owner_id": me["id"]})
    assert planted["id"] not in {c["id"] for c in client.get("/api/courses").json()}


def test_each_user_gets_their_own_demo_course(client: TestClient, make_client) -> None:
    mine = client.post("/api/demo")
    assert mine.status_code == 201
    bob = make_client("bob@example.com")
    theirs = bob.post("/api/demo")
    assert theirs.status_code == 201 and theirs.json()["id"] != mine.json()["id"]
    assert bob.post("/api/demo").json()["id"] == theirs.json()["id"]  # idempotent per user
    assert [c["id"] for c in client.get("/api/courses").json()] == [mine.json()["id"]]
