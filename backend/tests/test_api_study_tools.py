from fastapi.testclient import TestClient


def test_generate_quiz_hides_answers_until_graded(client: TestClient, ready_course: dict) -> None:
    cid = ready_course["id"]
    response = client.post(
        f"/api/courses/{cid}/quizzes",
        json={"num_questions": 5, "difficulty": "easy", "question_types": ["mcq", "true_false", "short_answer"]},
    )
    assert response.status_code == 201, response.text
    quiz = response.json()
    assert 1 <= quiz["question_count"] <= 5
    for question in quiz["questions"]:
        assert "correct_answer" not in question
        assert question["source"]["filename"]
        if question["question_type"] == "mcq":
            assert len(question["options"]) >= 2
        if question["question_type"] == "true_false":
            assert question["options"] == ["True", "False"]

    listed = client.get(f"/api/courses/{cid}/quizzes").json()
    assert listed[0]["id"] == quiz["id"] and listed[0]["attempt_count"] == 0


def test_quiz_attempt_grading(client: TestClient, ready_course: dict) -> None:
    quiz = client.post(
        f"/api/courses/{ready_course['id']}/quizzes", json={"num_questions": 4, "question_types": ["mcq"]}
    ).json()
    questions = quiz["questions"]
    assert all(q["question_type"] == "mcq" for q in questions)

    # First pass: answer everything with the first option to discover the right answers.
    first = client.post(
        f"/api/quizzes/{quiz['id']}/attempts", json={"answers": {q["id"]: q["options"][0] for q in questions}}
    )
    assert first.status_code == 201
    results = first.json()["results"]
    assert len(results) == len(questions)

    perfect = client.post(
        f"/api/quizzes/{quiz['id']}/attempts",
        json={"answers": {r["question_id"]: r["correct_answer"] for r in results}},
    ).json()
    assert perfect["score"] == 100.0
    assert perfect["correct_count"] == len(questions)
    assert all(r["explanation"] for r in perfect["results"])

    summary = client.get(f"/api/courses/{ready_course['id']}/quizzes").json()[0]
    assert summary["attempt_count"] == 2 and summary["best_score"] == 100.0

    blank = client.post(f"/api/quizzes/{quiz['id']}/attempts", json={"answers": {}}).json()
    assert blank["score"] == 0.0

    invalid = client.post(f"/api/quizzes/{quiz['id']}/attempts", json={"answers": {"bogus": "x"}})
    assert invalid.status_code == 400


def test_quiz_request_validation(client: TestClient, ready_course: dict) -> None:
    cid = ready_course["id"]
    assert client.post(f"/api/courses/{cid}/quizzes", json={"num_questions": 50}).status_code == 422
    assert client.post(f"/api/courses/{cid}/quizzes", json={"question_types": []}).status_code == 422
    assert client.post(f"/api/courses/{cid}/quizzes", json={"difficulty": "impossible"}).status_code == 422


def test_quiz_needs_materials(client: TestClient, course: dict) -> None:
    response = client.post(f"/api/courses/{course['id']}/quizzes", json={})
    assert response.status_code == 409


def test_topic_focused_quiz_uses_retrieval(client: TestClient, ready_course: dict) -> None:
    quiz = client.post(
        f"/api/courses/{ready_course['id']}/quizzes",
        json={"num_questions": 3, "topic": "regularization and dropout", "question_types": ["short_answer"]},
    ).json()
    assert quiz["topic"] == "regularization and dropout"
    assert quiz["questions"]


def test_flashcards_generation_and_spaced_repetition(client: TestClient, ready_course: dict) -> None:
    cid = ready_course["id"]
    response = client.post(f"/api/courses/{cid}/decks", json={"num_cards": 6})
    assert response.status_code == 201, response.text
    deck = response.json()
    assert 1 <= deck["card_count"] <= 6
    assert deck["due_count"] == deck["card_count"]
    assert all(card["front"] and card["back"] for card in deck["cards"])
    assert any(card["source"] for card in deck["cards"])

    study = client.get(f"/api/decks/{deck['id']}/study").json()
    card = study["cards"][0]

    good = client.post(f"/api/flashcards/{card['id']}/review", json={"rating": "good"}).json()
    assert good["repetitions"] == 1 and good["interval_days"] == 1
    assert good["due_at"] > card["due_at"]

    again = client.post(f"/api/flashcards/{card['id']}/review", json={"rating": "again"}).json()
    assert again["repetitions"] == 0 and again["lapses"] == 1

    after = client.get(f"/api/decks/{deck['id']}/study").json()
    assert card["id"] not in {c["id"] for c in after["cards"]}
    assert after["deck"]["reviewed_count"] == 1

    course = client.get(f"/api/courses/{cid}").json()
    assert course["stats"]["deck_count"] == 1
    assert course["stats"]["due_card_count"] == deck["card_count"] - 1

    bad_rating = client.post(f"/api/flashcards/{card['id']}/review", json={"rating": "meh"})
    assert bad_rating.status_code == 422

    reset = client.post(f"/api/decks/{deck['id']}/reset").json()
    assert reset["due_count"] == deck["card_count"] and reset["reviewed_count"] == 0

    assert client.delete(f"/api/decks/{deck['id']}").status_code == 204
    assert client.get(f"/api/decks/{deck['id']}").status_code == 404


def test_deleting_course_cascades_everything(client: TestClient, ready_course: dict) -> None:
    cid = ready_course["id"]
    client.post(f"/api/courses/{cid}/decks", json={"num_cards": 3})
    client.post(f"/api/courses/{cid}/quizzes", json={"num_questions": 2})
    client.post(f"/api/courses/{cid}/chat", json={"question": "What is momentum?"})
    assert client.delete(f"/api/courses/{cid}").status_code == 204
    assert client.get("/api/courses").json() == []
