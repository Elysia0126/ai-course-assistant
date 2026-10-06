"""Create a demo course from ../sample_data through the public API, then ask a sample question.

python scripts/seed_demo.py                         # API at http://localhost:8000
python scripts/seed_demo.py --api http://localhost:8010
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"
MIME = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".md": "text/markdown",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument(
        "--question", default="How should I choose a learning rate, and what happens if it is too large?"
    )
    args = parser.parse_args()

    client = httpx.Client(base_url=args.api.rstrip("/") + "/api", timeout=180)
    health = client.get("/health").json()
    print(f"API ok — llm={health['llm']['provider']}/{health['llm']['model']}, vector store={health['vector_store']}")

    course = client.post(
        "/courses",
        json={
            "name": "Machine Learning Foundations",
            "code": "ML 101",
            "term": "Fall 2026",
            "description": "Optimization, neural networks and regularization — demo course with sample materials.",
            "color": "indigo",
        },
    ).json()
    print(f"Created course {course['name']} ({course['id']})")

    samples = [p for p in sorted(SAMPLE_DIR.iterdir()) if p.suffix in MIME]
    files = [("files", (p.name, p.read_bytes(), MIME[p.suffix])) for p in samples]
    if not files:
        sys.exit(f"No sample files in {SAMPLE_DIR}. Run scripts/make_sample_data.py first.")
    upload = client.post(f"/courses/{course['id']}/documents", files=files)
    upload.raise_for_status()
    print(f"Uploaded {len(upload.json()['documents'])} files; waiting for indexing…")

    deadline = time.time() + 300
    while time.time() < deadline:
        docs = client.get(f"/courses/{course['id']}/documents").json()
        if all(d["status"] in {"ready", "failed"} for d in docs):
            break
        time.sleep(1)
    for doc in docs:
        detail = f"{doc['chunk_count']} chunks" if doc["status"] == "ready" else doc["error_message"]
        print(f"  {doc['status']:>7}  {doc['filename']}  ({detail})")

    answer = client.post(f"/courses/{course['id']}/chat", json={"question": args.question}).json()
    print(f"\nQ: {args.question}\n\n{answer['message']['content']}\n")
    for source in answer["message"]["sources"]:
        if source["cited"]:
            print(f"  [{source['index']}] {source['filename']} — {source['location']}")


if __name__ == "__main__":
    main()
