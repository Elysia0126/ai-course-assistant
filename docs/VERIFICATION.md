# Verification record

What was actually executed, where, and what was only configured. Last updated 2026-10-07.

Local machine: Windows 11, Python 3.12.15, Node.js 24.21, Next.js 16.3.8, PostgreSQL 16.2 + pgvector 0.6.2
(embedded via `pgserver`), local embeddings `BAAI/bge-small-en-v1.5` (fastembed/ONNX). Remote: GitHub Actions
`ubuntu-latest` with the `pgvector/pgvector:pg17` service container.

## Automated checks

| Check | Where | Result |
|---|---|---|
| Backend tests on SQLite (hash embeddings, offline generator) | local + CI | **72 passed** |
| Same 72 tests on PostgreSQL + pgvector (HNSW, BM25 over `tsvector`/GIN, JSONB) | local (PG 16) + CI (PG 17) | **72 passed** |
| Combined statement coverage (SQLite + PostgreSQL runs) | local + CI (gate ≥ 85%) | **92.4%** |
| Ruff lint + format | local + CI | clean |
| Frontend ESLint, `tsc --noEmit`, Vitest (14 tests incl. the API proxy), production build | local + CI | passed |
| Retrieval evaluation, 33 labelled questions ([details](../evaluation/README.md)) | local (3 configurations) + CI gate | hybrid Recall@5 = 1.00, MRR = 0.92 (bge-small + pgvector) |
| Docker images (`docker compose build`) | CI | built |
| Alembic upgrade → downgrade → upgrade, schema matches models | local + CI | passed |

## End-to-end (real browser)

`backend/scripts/capture_screenshots.py` drives Microsoft Edge (Playwright) against the production build
(`next start`) → same-origin `/api` proxy → FastAPI → PostgreSQL + pgvector, and asserts on each step:

1. Dashboard → **Demo course** button creates and indexes the sample course (PDF, PPTX with notes, Markdown).
2. Materials page lists 3 ready documents; the retrieval inspector returns hybrid results with vector/BM25/RRF scores.
3. A question streams over SSE through the proxy; cited sources render; the **View** button opens the full passage.
4. Quiz: generate → answer every question → submit → graded results with explanations and sources.
5. Flashcards: generate → study → flip → rate *Good* → the session advances.
6. Mobile 390 × 844: no horizontal overflow on any page; source cards are not clipped.

The screenshots in [`docs/screenshots/`](screenshots) are produced by this run.

Other live checks through the proxy: SSE delivered 65 incremental `token` events for one answer (not buffered),
a cross-origin `POST` was refused with 403, and the demo endpoint is idempotent.

## Bugs found by verification (and fixed)

| Found by | Problem | Fix |
|---|---|---|
| First live start | `CORS_ORIGINS=http://localhost:3000` (as in `.env.example`) crashed startup — pydantic-settings JSON-decodes list fields | `NoDecode` + comma parser, regression test |
| Retrieval evaluation | PostgreSQL keyword ranking used `ts_rank_cd` (no IDF): keyword Recall@1 0.64 vs 0.82 for BM25 on SQLite | BM25 computed from the GIN-indexed `tsvector` → 0.86 |
| E2E screenshots | Offline generator produced questions from "Speaker notes:" and "Lecture 3:" labels; pronoun-led sentences as answers | Structural-label and pronoun filters, tests |
| E2E mobile check | Grid columns grew to their content's min-width → 78–299 px horizontal overflow; source cards clipped | `minmax(0,1fr)` columns, clipping assertion in E2E |
| Restart after a killed session | Embedded Postgres crash recovery outlasted `pg_ctl`'s 10 s timeout | `dev_db.py` waits and re-attaches |

## Not verified

- **Real LLM calls.** No Anthropic or OpenAI-compatible API key was available. The Claude and OpenAI-compatible
  adapters are tested against fake SDK clients (request shape, streaming, structured output, refusals, retries,
  embedding dimensions), and all runs above used the offline generator. Answer quality with a real model is unmeasured.
- **Running containers.** Images build in CI, but `docker compose up` (container start-up, health checks, volumes)
  has not been run — no Docker engine on the development machine.
- **Scale.** Everything was exercised with a 23-chunk demo course; there are no load or large-corpus tests.
- **Other browsers / macOS / Linux desktop.** E2E ran on Edge (Chromium) on Windows only.
