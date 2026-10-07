"""Retrieval evaluation and ablation over the labelled demo-course question set.

Indexes sample_data/ through the real API, then asks every question in
evaluation/retrieval_questions.json with vector-only, keyword-only and hybrid (RRF) retrieval and reports
Recall@k, MRR, and how well low-confidence detection separates unanswerable questions.

    python scripts/evaluate_retrieval.py                                   # SQLite + hashing embeddings (fast, CI)
    python scripts/evaluate_retrieval.py --embedding fastembed             # local semantic model
    python scripts/evaluate_retrieval.py --embedding fastembed --database-url postgresql+psycopg://…  # production path

This is a small, hand-labelled set over a 23-chunk demo course — useful for comparing retrieval
strategies and catching regressions, not a general accuracy claim.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

MODES = ("vector", "keyword", "hybrid")
KS = (1, 3, 5)
MIME = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".md": "text/markdown",
}


def is_relevant(hit: dict[str, Any], targets: list[dict[str, Any]]) -> bool:
    for target in targets:
        if hit["filename"] != target["file"]:
            continue
        if "page" in target and hit["page_number"] == target["page"]:
            return True
        if "section" in target and hit["section"] == target["section"]:
            return True
    return False


def evaluate(embedding: str, database_url: str | None, top_k: int = 10) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    dataset = json.loads((ROOT / "evaluation" / "retrieval_questions.json").read_text(encoding="utf-8"))
    questions = dataset["questions"]

    with tempfile.TemporaryDirectory(prefix="aca-eval-") as tmp:
        settings = Settings(
            _env_file=None,
            app_env="test",
            log_level="WARNING",
            database_url=database_url or f"sqlite:///{Path(tmp, 'eval.db').as_posix()}",
            upload_dir=Path(tmp) / "uploads",
            embedding_provider=embedding,
            llm_provider="offline",
        )
        with TestClient(create_app(settings)) as client:
            course = client.post("/api/courses", json={"name": "Retrieval evaluation"}).json()
            try:
                files = [
                    ("files", (p.name, p.read_bytes(), MIME[p.suffix]))
                    for p in sorted((ROOT / "sample_data").iterdir())
                    if p.suffix in MIME
                ]
                client.post(f"/api/courses/{course['id']}/documents", files=files).raise_for_status()
                documents = client.get(f"/api/courses/{course['id']}/documents").json()
                assert all(d["status"] == "ready" for d in documents), documents
                n_chunks = sum(d["chunk_count"] for d in documents)

                rows = []
                for item in questions:
                    row: dict[str, Any] = {"id": item["id"], "category": item["category"], "ranks": {}}
                    for mode in MODES:
                        response = client.post(
                            f"/api/courses/{course['id']}/search",
                            json={"query": item["question"], "top_k": top_k, "mode": mode},
                        ).json()
                        hits = response["results"]
                        rank = next((i for i, h in enumerate(hits, 1) if is_relevant(h, item["relevant"])), None)
                        row["ranks"][mode] = rank
                        if mode == "hybrid":
                            row["low_confidence"] = response["low_confidence"]
                            row["best_vector_score"] = response["best_vector_score"]
                            row["top_hit"] = f"{hits[0]['filename']} · {hits[0]['location']}" if hits else None
                    rows.append(row)
            finally:
                client.delete(f"/api/courses/{course['id']}")

    def summarize(subset: list[dict[str, Any]], mode: str) -> dict[str, float]:
        if not subset:
            return {}
        out = {
            f"recall@{k}": sum(1 for r in subset if r["ranks"][mode] and r["ranks"][mode] <= k) / len(subset)
            for k in KS
        }
        out["mrr"] = sum(1 / r["ranks"][mode] for r in subset if r["ranks"][mode]) / len(subset)
        return {key: round(value, 3) for key, value in out.items()}

    answerable = [r for r in rows if r["category"] != "unanswerable"]
    unanswerable = [r for r in rows if r["category"] == "unanswerable"]
    metrics = {
        mode: {
            "all": summarize(answerable, mode),
            "lexical": summarize([r for r in answerable if r["category"] == "lexical"], mode),
            "paraphrase": summarize([r for r in answerable if r["category"] == "paraphrase"], mode),
        }
        for mode in MODES
    }
    abstention = {
        "unanswerable_flagged": round(sum(r["low_confidence"] for r in unanswerable) / max(len(unanswerable), 1), 3),
        "answerable_false_alarms": round(sum(r["low_confidence"] for r in answerable) / max(len(answerable), 1), 3),
    }
    return {
        "config": {
            "embedding": embedding,
            "embedding_model": settings.embedding_model if embedding != "hash" else "feature-hash-384",
            "database": "postgresql+pgvector" if settings.is_postgres else "sqlite",
            "chunks": n_chunks,
            "questions": {
                c: sum(1 for q in questions if q["category"] == c) for c in ("lexical", "paraphrase", "unanswerable")
            },
            "top_k": top_k,
        },
        "metrics": metrics,
        "low_confidence_detection": abstention,
        "rows": rows,
    }


def markdown(report: dict[str, Any]) -> str:
    cfg = report["config"]
    lines = [
        f"**{cfg['embedding_model']} · {cfg['database']} · {cfg['chunks']} chunks**",
        "",
        "| Retriever | Recall@1 | Recall@3 | Recall@5 | MRR | Recall@1 (paraphrase) | MRR (paraphrase) |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode in MODES:
        a, p = report["metrics"][mode]["all"], report["metrics"][mode]["paraphrase"]
        lines.append(
            f"| {mode} | {a['recall@1']:.2f} | {a['recall@3']:.2f} | {a['recall@5']:.2f} | {a['mrr']:.2f} "
            f"| {p['recall@1']:.2f} | {p['mrr']:.2f} |"
        )
    d = report["low_confidence_detection"]
    lines += [
        "",
        f"Low-confidence flag: {d['unanswerable_flagged']:.0%} of unanswerable questions flagged, "
        f"{d['answerable_false_alarms']:.0%} false alarms on answerable ones.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--embedding", choices=["hash", "fastembed", "openai"], default="hash")
    parser.add_argument("--database-url", default=None, help="defaults to a temporary SQLite database")
    parser.add_argument("--output", type=Path, default=None, help="write the full JSON report here")
    parser.add_argument("--min-hybrid-recall5", type=float, default=None, help="fail (exit 1) below this")
    args = parser.parse_args()

    report = evaluate(args.embedding, args.database_url)
    print(markdown(report))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote {args.output}")
    recall5 = report["metrics"]["hybrid"]["all"]["recall@5"]
    if args.min_hybrid_recall5 is not None and recall5 < args.min_hybrid_recall5:
        sys.exit(f"Hybrid Recall@5 {recall5:.3f} is below the required {args.min_hybrid_recall5:.3f}")


if __name__ == "__main__":
    main()
