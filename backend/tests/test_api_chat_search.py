import json

from fastapi.testclient import TestClient


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_search_returns_hybrid_scores_and_locations(client: TestClient, ready_course: dict) -> None:
    response = client.post(f"/api/courses/{ready_course['id']}/search", json={"query": "warmup learning rate"})
    assert response.status_code == 200
    top = response.json()["results"][0]
    assert top["filename"] == "Lecture03_Gradient_Descent.pdf"
    assert top["page_number"] == 2
    assert top["location"] == "page 2"
    assert top["keyword_score"] > 0 and top["vector_score"] > 0


def test_search_modes_for_ablation(client: TestClient, ready_course: dict) -> None:
    url = f"/api/courses/{ready_course['id']}/search"
    keyword = client.post(url, json={"query": "warmup learning rate", "mode": "keyword"}).json()["results"]
    assert keyword and keyword[0]["page_number"] == 2
    # Keyword-only retrieval returns nothing for a query sharing no terms with the material…
    assert client.post(url, json={"query": "zebra xylophone", "mode": "keyword"}).json()["results"] == []
    # …while vector-only always returns nearest neighbours (which is why low_confidence exists).
    vector = client.post(url, json={"query": "zebra xylophone", "mode": "vector"}).json()
    assert vector["results"] and vector["low_confidence"] is True
    assert client.post(url, json={"query": "x", "mode": "magic"}).status_code == 422


def test_search_can_be_scoped_to_documents(client: TestClient, ready_course: dict) -> None:
    docs = client.get(f"/api/courses/{ready_course['id']}/documents").json()
    pptx = next(d for d in docs if d["file_type"] == "pptx")
    results = client.post(
        f"/api/courses/{ready_course['id']}/search",
        json={"query": "learning rate", "document_ids": [pptx["id"]]},
    ).json()["results"]
    assert results and {r["document_id"] for r in results} == {pptx["id"]}


def test_chat_answers_with_cited_sources_and_persists_session(client: TestClient, ready_course: dict) -> None:
    cid = ready_course["id"]
    response = client.post(f"/api/courses/{cid}/chat", json={"question": "What is backpropagation?"})
    assert response.status_code == 200, response.text
    body = response.json()
    message = body["message"]
    assert "chain rule" in message["content"]
    cited = [s for s in message["sources"] if s["cited"]]
    assert cited, "answer should cite at least one source"
    assert cited[0]["filename"] == "Lecture05_Neural_Networks.pptx"
    assert cited[0]["location"] == "slide 1"
    assert message["meta"]["provider"] == "offline"

    follow_up = client.post(
        f"/api/courses/{cid}/chat", json={"question": "And what is ReLU?", "session_id": body["session_id"]}
    )
    assert follow_up.status_code == 200
    assert follow_up.json()["session_id"] == body["session_id"]

    sessions = client.get(f"/api/courses/{cid}/chat/sessions").json()
    assert len(sessions) == 1 and sessions[0]["message_count"] == 4
    transcript = client.get(f"/api/chat/sessions/{body['session_id']}").json()
    assert [m["role"] for m in transcript["messages"]] == ["user", "assistant", "user", "assistant"]
    assert transcript["messages"][1]["sources"]


def test_chat_stream_emits_ordered_events(client: TestClient, ready_course: dict) -> None:
    response = client.post(f"/api/courses/{ready_course['id']}/chat/stream", json={"question": "What does dropout do?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta" and names[1] == "sources" and names[-1] == "done"
    assert names.count("token") > 3
    streamed = "".join(data["text"] for name, data in events if name == "token")
    assert streamed.strip() == events[-1][1]["content"]
    assert "Dropout" in streamed


def test_chat_requires_processed_materials(client: TestClient, course: dict) -> None:
    response = client.post(f"/api/courses/{course['id']}/chat/stream", json={"question": "Anything?"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_materials"


def test_chat_validates_input_and_session(client: TestClient, ready_course: dict) -> None:
    cid = ready_course["id"]
    assert client.post(f"/api/courses/{cid}/chat", json={"question": "   "}).status_code == 422
    unknown = client.post(f"/api/courses/{cid}/chat/stream", json={"question": "Hi", "session_id": "nope"})
    assert unknown.status_code == 404
    assert client.post("/api/courses/missing/chat", json={"question": "Hi"}).status_code == 404


def test_off_topic_question_is_flagged_low_confidence(client: TestClient, ready_course: dict) -> None:
    body = client.post(
        f"/api/courses/{ready_course['id']}/chat", json={"question": "Who won the 1998 football world cup?"}
    ).json()
    assert body["low_confidence"] is True


def test_delete_chat_session(client: TestClient, ready_course: dict) -> None:
    body = client.post(f"/api/courses/{ready_course['id']}/chat", json={"question": "What is Adam?"}).json()
    assert client.delete(f"/api/chat/sessions/{body['session_id']}").status_code == 204
    assert client.get(f"/api/chat/sessions/{body['session_id']}").status_code == 404
