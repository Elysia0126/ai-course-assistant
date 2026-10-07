from fastapi.testclient import TestClient

from tests import factories
from tests.conftest import upload


def test_health_reports_providers(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["llm"]["provider"] == "offline"
    assert body["embeddings"] == {
        "provider": "hash",
        "model": "feature-hash-384",
        "dim": 384,
        "signature": "hash:feature-hash-384:384",
    }


def test_security_headers(client: TestClient) -> None:
    headers = client.get("/api/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-request-id"]


def test_course_crud_and_validation(client: TestClient) -> None:
    created = client.post("/api/courses", json={"name": "  Algorithms ", "code": "CS 3510", "color": "emerald"})
    assert created.status_code == 201
    course = created.json()
    assert course["name"] == "Algorithms"
    assert course["stats"]["document_count"] == 0

    assert client.get("/api/courses").json()[0]["id"] == course["id"]

    updated = client.patch(f"/api/courses/{course['id']}", json={"term": "Fall 2026"})
    assert updated.json()["term"] == "Fall 2026"

    bad = client.post("/api/courses", json={"name": ""})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"

    bad_color = client.post("/api/courses", json={"name": "X", "color": "neon"})
    assert bad_color.status_code == 422

    assert client.delete(f"/api/courses/{course['id']}").status_code == 204
    missing = client.get(f"/api/courses/{course['id']}")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "Course not found.", "details": None}}


def test_upload_indexes_documents_with_locations(client: TestClient, ready_course: dict) -> None:
    documents = client.get(f"/api/courses/{ready_course['id']}/documents").json()
    by_type = {d["file_type"]: d for d in documents}
    assert by_type["pdf"]["page_count"] == 3
    assert by_type["pptx"]["page_count"] == 2
    assert all(d["chunk_count"] > 0 for d in documents)

    chunks = client.get(f"/api/documents/{by_type['pdf']['id']}/chunks", params={"page": 2}).json()
    assert chunks and all(c["page_number"] == 2 for c in chunks)
    assert "Warmup" in chunks[0]["content"]

    course = client.get(f"/api/courses/{ready_course['id']}").json()
    assert course["stats"]["ready_document_count"] == 3
    assert course["stats"]["chunk_count"] >= 3

    file_response = client.get(f"/api/documents/{by_type['pdf']['id']}/file")
    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "application/pdf"
    assert file_response.headers["content-disposition"].startswith("inline")


def test_upload_rejects_unsupported_empty_fake_and_duplicate_files(client: TestClient, course: dict) -> None:
    cid = course["id"]
    unsupported = upload(client, cid, ("photo.png", b"\x89PNG....", "image/png"))
    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "unsupported_file_type"

    legacy = upload(client, cid, ("old.ppt", b"\xd0\xcf\x11\xe0", "application/vnd.ms-powerpoint"))
    assert legacy.status_code == 415
    assert ".pptx" in legacy.json()["error"]["message"]

    empty = upload(client, cid, ("empty.txt", b"", "text/plain"))
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "empty_file"

    fake_pdf = upload(client, cid, ("fake.pdf", b"hello world", "application/pdf"))
    assert fake_pdf.status_code == 415

    ok = upload(client, cid, ("notes.md", factories.MARKDOWN, "text/markdown"))
    assert ok.status_code == 201
    duplicate = upload(client, cid, ("copy.md", factories.MARKDOWN, "text/markdown"))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_document"


def test_partial_upload_success_reports_per_file_errors(client: TestClient, course: dict) -> None:
    response = upload(
        client,
        course["id"],
        ("good.md", factories.MARKDOWN, "text/markdown"),
        ("bad.exe", b"MZ", "application/octet-stream"),
    )
    assert response.status_code == 201
    body = response.json()
    assert [d["filename"] for d in body["documents"]] == ["good.md"]
    assert body["errors"][0]["filename"] == "bad.exe"


def test_upload_size_limit(client: TestClient, course: dict, settings) -> None:
    big = b"a " * (settings.max_upload_bytes // 2 + 10)
    response = upload(client, course["id"], ("big.txt", big, "text/plain"))
    assert response.status_code == 413


def test_scanned_pdf_fails_with_message_and_can_be_reprocessed(client: TestClient, course: dict) -> None:
    response = upload(client, course["id"], ("scan.pdf", factories.make_blank_pdf(), "application/pdf"))
    assert response.status_code == 201
    doc_id = response.json()["documents"][0]["id"]
    document = client.get(f"/api/documents/{doc_id}").json()
    assert document["status"] == "failed"
    assert "scanned" in document["error_message"]

    retry = client.post(f"/api/documents/{doc_id}/reprocess")
    assert retry.status_code == 202
    assert client.get(f"/api/documents/{doc_id}").json()["status"] == "failed"


def test_delete_document_removes_chunks(client: TestClient, ready_course: dict) -> None:
    documents = client.get(f"/api/courses/{ready_course['id']}/documents").json()
    before = client.get(f"/api/courses/{ready_course['id']}").json()["stats"]["chunk_count"]
    assert client.delete(f"/api/documents/{documents[0]['id']}").status_code == 204
    after = client.get(f"/api/courses/{ready_course['id']}").json()["stats"]["chunk_count"]
    assert after < before
    assert client.get(f"/api/documents/{documents[0]['id']}").status_code == 404
