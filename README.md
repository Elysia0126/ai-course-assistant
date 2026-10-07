# AI Course Assistant

**Upload your lecture slides, PDFs and notes — then ask questions with page-level citations, generate quizzes, and
study flashcards on a spaced-repetition schedule. Everything is grounded in *your* course materials.**

[![CI](https://github.com/Elysia0126/ai-course-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/Elysia0126/ai-course-assistant/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.142-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

![Ask a question and get an answer that cites the exact slide and page](docs/screenshots/chat.png)

> The screenshots show the built-in **offline mode** (no API key configured), where answers are extracted
> sentences. With `ANTHROPIC_API_KEY` (or any OpenAI-compatible provider) set, the same UI streams generated,
> cited explanations — nothing else changes.

---

## Contents

- [Features](#features) · [Screenshots](#screenshots) · [Retrieval quality](#retrieval-quality) · [Architecture](#architecture)
- [Tech stack](#tech-stack) · [Design decisions](#key-design-decisions) · [Project structure](#project-structure)
- [Quick start (Docker)](#quick-start-with-docker) · [Local development](#local-development)
- [Configuration](#configuration) · [Database & migrations](#database--migrations) · [API](#api)
- [Testing](#testing) · [Deployment](#deployment) · [Known limitations](#known-limitations) · [Roadmap](#roadmap)
- [Resume / CV description](#resume--cv-description)

## Features

| | |
|---|---|
| 📚 **Course & material management** | Courses with **PDF, PowerPoint (.pptx), Word (.docx), Markdown, TXT** uploads (drag & drop, multi-file, progress). One-click **demo course**. Content sniffing, size/page/text limits, zip-bomb protection, per-course de-duplication. |
| 🧩 **Location-aware parsing & chunking** | PDFs page by page, slides slide by slide (incl. **speaker notes, tables and grouped shapes**), Markdown/Word by heading. Chunks never cross a page boundary, so every citation is exact. |
| 🔎 **Hybrid retrieval** | **pgvector HNSW** cosine search + **BM25 over PostgreSQL's full-text index**, fused with **Reciprocal Rank Fusion** — [evaluated](#retrieval-quality) on a labelled question set. A *retrieval inspector* shows vector, BM25 and fused scores and switches between retrievers. |
| 💬 **Cited Q&A (RAG)** | Answers stream token-by-token over **Server-Sent Events** and cite sources inline (`[1]`, `[2]`). Click a citation to highlight the source, **view the exact retrieved passage**, or open the PDF **at the cited page**. Off-topic questions are flagged and refused rather than answered from thin air. Multi-turn chat sessions are saved. |
| 📝 **Quiz generator** | Multiple-choice, true/false and short-answer questions at three difficulty levels, optionally focused on a topic or documents. Answers stay server-side until submission; grading returns explanations and the source page per question. |
| 🃏 **Flashcards with spaced repetition** | Decks reviewed with **SM-2** (Again / Hard / Good / Easy with next-interval preview and keyboard shortcuts); **export to Anki**. |
| 🔌 **Pluggable providers** | LLM: **Claude** (Anthropic SDK, streaming, structured outputs), any **OpenAI-compatible** API (OpenAI, DeepSeek, Qwen, Ollama, vLLM…), or a deterministic **offline** mode. Embeddings: local **fastembed** (ONNX, free), OpenAI-compatible, or hashing (tests). |
| 🛡️ **Safety & robustness** | Prompt-injection guard (retrieved text is data, not instructions); **index versioning** (vectors from a different embedding model are never mixed — one-click re-index); background ingestion state machine with crash recovery; same-origin API proxy with CSRF check and optional service token; consistent JSON errors. |

## Screenshots

| Course dashboard | Materials + retrieval inspector |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Materials](docs/screenshots/materials.png) |
| **Exact retrieved passage behind a citation** | **Quiz with grading & sources** |
| ![Passage viewer](docs/screenshots/passage.png) | ![Quiz](docs/screenshots/quiz.png) |
| **Flashcard study (SM-2)** | **Mobile (390 px)** |
| ![Flashcards](docs/screenshots/flashcards.png) | <img src="docs/screenshots/mobile.png" alt="Mobile layout" width="260"> |

All screenshots come from an automated end-to-end run in a real browser (`backend/scripts/capture_screenshots.py`).

## Retrieval quality

A hand-labelled set of **33 questions** over the demo course — 16 using the material's own terms, 12 paraphrased
the way a student would ask, 5 not covered at all — with relevance judged by **file + page/slide/section**, i.e.
whether the citation location itself is right. Production configuration (bge-small embeddings, PostgreSQL + pgvector):

| Retriever | Recall@1 | Recall@3 | Recall@5 | MRR | Paraphrase MRR |
|---|---|---|---|---|---|
| vector only | 0.75 | 0.89 | **1.00** | 0.83 | 0.73 |
| keyword only (BM25) | **0.86** | **0.96** | 0.96 | **0.92** | **0.85** |
| **hybrid (RRF)** | **0.86** | **0.96** | **1.00** | **0.92** | **0.85** |

Low-confidence detection flagged **5/5** unanswerable questions with **0/28** false alarms. Hybrid is the only
retriever that puts every answerable question in the top 5. The evaluation also caught a real bug: Postgres'
`ts_rank_cd` has no IDF, so keyword search initially scored Recall@1 0.64 — replaced by BM25 computed from the
GIN-indexed `tsvector`. Small corpus, developer-written questions: treat it as an ablation and regression harness, not
a general accuracy claim. Details, all configurations and caveats: [`evaluation/`](evaluation/README.md). CI fails if
hybrid Recall@5 drops below 0.9.

## Architecture

```mermaid
flowchart LR
    subgraph Web["Next.js 16"]
        UI["Dashboard · Materials · Ask · Quiz · Flashcards"]
        Proxy["/api proxy<br/>(streams, CSRF check, service token)"]
    end

    subgraph API["FastAPI backend"]
        Routes["REST + SSE routes"]
        Ingest["Ingestion<br/>parse → chunk → embed"]
        Retriever["Hybrid retriever<br/>HNSW + BM25 → RRF"]
        Gen["Generation<br/>Claude · OpenAI-compatible · offline"]
        Study["Quiz grading · SM-2"]
    end

    subgraph Data["PostgreSQL + pgvector"]
        Tables[("courses · documents · chunks<br/>chats · quizzes · flashcards")]
        HNSW[["HNSW index (cosine)"]]
        GIN[["GIN index (tsvector)"]]
    end

    Files[("Upload storage")]
    Embed["Embeddings<br/>fastembed (local ONNX) / OpenAI"]
    LLM["LLM API"]

    UI --> Proxy
    Proxy -- "JSON / multipart / SSE" --> Routes
    Routes --> Ingest & Retriever & Study
    Ingest --> Files
    Ingest --> Embed
    Ingest --> Tables
    Retriever --> HNSW & GIN
    Retriever --> Gen
    Gen --> LLM
    Study --> Tables
```

The browser only talks to the Next.js server; its `/api/*` route handler streams requests and responses to FastAPI
(`BACKEND_URL`, a runtime setting), adds the optional `APP_API_TOKEN` server-side and refuses cross-origin writes.

**Ingestion** — `POST /documents` validates and stores the file, returns immediately (`201`), and a background task
parses it into location-tagged sections, splits them into chunks, embeds each with a *contextual header*
(`document title — section`), records the embedding model's signature, and swaps the chunks in atomically while
marking the document `ready`.

**Question answering**

```mermaid
sequenceDiagram
    participant UI as Browser
    participant API as FastAPI (via /api proxy)
    participant DB as Postgres (pgvector + FTS)
    participant LLM as LLM provider
    UI->>API: POST /courses/{id}/chat/stream {question, session_id?, document_ids?}
    API->>DB: check course, materials and index version
    API->>DB: save user message (new session if needed)
    API-->>UI: event: meta
    API->>DB: top-30 by cosine (HNSW) ∥ top-30 by BM25 over the GIN index
    API->>API: Reciprocal Rank Fusion → top-k chunks, low-confidence check
    API-->>UI: event: sources (file, page/slide, snippet, scores, low_confidence)
    API->>LLM: system prompt + numbered <source> blocks (+ low-confidence note) + history
    loop streaming
        LLM-->>API: text delta
        API-->>UI: event: token
    end
    API->>API: validate [n] citations against retrieved sources
    API->>DB: save answer + source snapshot
    API-->>UI: event: done (message id, cited ids, latency)
```

## Tech stack

| Layer | Choices |
|---|---|
| Frontend | Next.js 16 (App Router, Turbopack, route-handler proxy), React 19, TypeScript, Tailwind CSS 4, react-markdown + KaTeX, lucide icons, sonner |
| Backend | Python 3.12, FastAPI, Pydantic v2 / pydantic-settings, SQLAlchemy 2, Alembic, Uvicorn |
| Data | PostgreSQL + **pgvector** (HNSW, cosine), full-text `tsvector` + GIN with BM25 scoring; SQLite fallback (numpy + in-process BM25) |
| Parsing | pypdf, python-pptx, python-docx, Markdown/TXT with encoding detection |
| AI | Anthropic Python SDK (Claude: streaming, structured outputs, refusal fallbacks), OpenAI SDK (any compatible endpoint), fastembed (BAAI/bge-small-en-v1.5, ONNX) |
| Quality | pytest (72 tests on SQLite **and** pgvector, 92% coverage), Vitest + Testing Library (14), Playwright E2E incl. mobile, retrieval benchmark, Ruff, ESLint, `tsc` |
| Ops | Docker (non-root images, health checks), docker compose, GitHub Actions CI |

## Key design decisions

- **Citations you can trust.** Chunks never span pages/slides and store `page_number` + `section`; the model sees
  numbered `<source id="n" file=… location="page 4">` blocks; the backend keeps only citation numbers that refer to
  retrieved sources and stores a **snapshot** of each, so old answers survive re-indexing. Users can open the exact
  passage behind any citation.
- **Hybrid retrieval with RRF, measured.** Dense vectors handle paraphrases; BM25 handles exact jargon and symbols;
  RRF merges the rankings without calibrating their scales. On Postgres, BM25 runs on the full-text index: candidates
  via GIN, one index lookup per query term for document frequency, term frequencies parsed from each `tsvector`.
- **Know when not to answer.** If the best cosine similarity is below a per-model threshold, the UI warns, the LLM is
  told the excerpts are weak, and offline mode refuses instead of pasting unrelated text.
- **Retrieved text is untrusted.** Every prompt states that `<source>` content is reference material and that
  instructions inside it must be ignored.
- **Never mix vector spaces.** Each document records `provider:model:dim` of its embeddings; searching documents
  indexed by another model returns `409 index_outdated` and the UI offers one-click re-indexing.
- **Provider-agnostic generation at the task level.** Backends implement `stream_answer`, `generate_quiz` and
  `generate_flashcards`. Claude uses the official SDK with streaming, effort control, refusal handling and
  server-side fallbacks, plus Pydantic **structured outputs**; OpenAI-compatible providers use JSON mode with
  validation and repair retries; an **offline backend** implements the same contract heuristically — so the app,
  demo, tests and evaluation run without any key.
- **Never trust model output blindly.** Generated questions are validated and repaired (MCQ answer must be an option;
  options shuffled; true/false normalised; duplicates and invalid `source_id`s dropped).
- **Portable persistence.** A custom `EmbeddingVector` type maps to `vector(384)` on Postgres and JSON elsewhere;
  the same Alembic migrations and the same tests run on both.
- **Operational details.** Interrupted ingestion is marked `failed` for retry on startup; uploads are sniffed and
  bounded (size, pages, extracted text, zip expansion); duplicate uploads are race-safe via a unique constraint;
  security headers on every response; errors are `{"error": {"code", "message", "details"}}`.

## Project structure

```
ai-course-assistant/
├── backend/
│   ├── app/
│   │   ├── api/routes/        # courses, demo, documents (+chunks, re-index), chat (+SSE, search), quizzes, flashcards, health
│   │   ├── core/              # settings, error model + handlers, logging
│   │   ├── db/                # engine/session, cross-dialect types (EmbeddingVector, UTCDateTime)
│   │   ├── models/ · schemas/ # SQLAlchemy models · Pydantic request/response models
│   │   ├── services/
│   │   │   ├── parsing.py     # PDF / PPTX / DOCX / MD / TXT → location-tagged sections (+ limits)
│   │   │   ├── chunking.py    # structure-aware splitter with overlap
│   │   │   ├── embeddings.py  # fastembed · OpenAI · hashing providers + signatures
│   │   │   ├── ingestion.py   # background pipeline + status state machine
│   │   │   ├── retrieval.py   # pgvector + BM25-on-FTS / numpy + BM25, RRF, index-version check
│   │   │   ├── chat.py        # RAG orchestration, citation validation, sessions
│   │   │   ├── quizzes.py · flashcards.py · srs.py
│   │   │   └── llm/           # prompts, Claude / OpenAI-compatible / offline backends
│   │   └── main.py            # app factory (lifespan, CORS, token check, security headers, routers)
│   ├── alembic/               # migrations (pgvector, HNSW + GIN indexes, embedding signatures)
│   ├── scripts/               # dev_db · seed_demo · evaluate_retrieval · capture_screenshots · make_sample_data
│   └── tests/                 # 72 pytest tests (SQLite + optional PostgreSQL)
├── frontend/
│   ├── src/app/               # dashboard, /courses/[courseId]/{materials,ask,quiz,flashcards}, api/[...path] proxy
│   ├── src/components/        # UI kit, Markdown + citation chips, source cards + passage viewer, scope picker…
│   └── src/lib/               # typed API client, SSE parser, citation / SM-2 / export helpers (+ tests)
├── evaluation/                # labelled retrieval questions, results, write-up
├── sample_data/               # demo course: 6-page PDF lecture, 8-slide PPTX with notes, Markdown guide
├── docs/                      # VERIFICATION.md, screenshots
├── docker-compose.yml · .env.example · .github/workflows/ci.yml
```

## Quick start with Docker

Requirements: Docker with Compose v2.24+.

```bash
cp .env.example .env          # optional: ANTHROPIC_API_KEY, APP_API_TOKEN, ...
docker compose up --build
```

Open <http://localhost:3000> and click **Demo course** to load and index the sample materials. API docs are at
<http://127.0.0.1:8000/docs> (the API is bound to loopback; the browser goes through the frontend's proxy). The
backend image bakes in the local embedding model and runs `alembic upgrade head` before starting; Postgres data and
uploads live in named volumes.

## Local development

Requirements: **Python 3.11+** (3.12 recommended), **Node.js 20.9+**, and PostgreSQL with pgvector (any option below).

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp ../.env.example .env            # then edit DATABASE_URL / API keys
```

| Database option | How | Notes |
|---|---|---|
| **Docker pgvector** (recommended) | `docker compose up -d db` (add `ports: ["5432:5432"]` to the `db` service) | Matches production |
| **Embedded Postgres, no Docker** | `python scripts/dev_db.py --write-env` | PostgreSQL 16 + pgvector from a pip package (`pgserver`, Python ≤ 3.12); writes `DATABASE_URL` into `backend/.env` |
| **SQLite** (quick look) | `DATABASE_URL=sqlite:///./data/dev.db` | In-process numpy + BM25 retriever |

```bash
uvicorn app.main:app --reload            # http://localhost:8000/docs — migrations run automatically
```

The first run downloads the ~65 MB embedding model (`BAAI/bge-small-en-v1.5`, ONNX) into `backend/data/models`.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local               # BACKEND_URL=http://127.0.0.1:8000
npm run dev                              # http://localhost:3000 → "Demo course"
```

## Configuration

All backend settings are environment variables (or `.env` / `backend/.env`); see [`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/course_assistant` | SQLAlchemy URL (PostgreSQL + pgvector, or SQLite) |
| `AUTO_MIGRATE` | `true` | Run Alembic migrations on startup (`false` in the Docker image, which migrates explicitly) |
| `APP_API_TOKEN` | — | Optional shared secret; when set, all `/api` routes except health require `Authorization: Bearer …`. Set the same value for the frontend |
| `CORS_ORIGINS` | `http://localhost:3000` | Only needed when browsers call the API directly (`NEXT_PUBLIC_API_URL`) |
| `MAX_UPLOAD_MB` / `MAX_PAGES` / `MAX_DOCUMENT_CHARS` / `MAX_UNZIPPED_MB` | `25` / `500` / `2000000` / `200` | Upload and parsing limits |
| `UPLOAD_DIR` / `DEMO_DIR` | `backend/data/uploads` / `sample_data` | Original files / demo-course materials |
| `LLM_PROVIDER` | `auto` | `auto` · `anthropic` · `openai` · `offline` (`auto`: Anthropic → OpenAI-compatible → offline, based on which keys exist) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / `claude-opus-5-5` | Claude |
| `ANTHROPIC_EFFORT` / `ANTHROPIC_FALLBACKS` | `medium` / `true` | Effort level (blank for models without it) / server-side refusal fallback |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | — | Any OpenAI-compatible endpoint (e.g. DeepSeek `https://api.deepseek.com/v1` + `deepseek-chat`, Ollama `http://localhost:11434/v1`) |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `fastembed` / `BAAI/bge-small-en-v1.5` / `384` | For Chinese/multilingual notes: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` / `RETRIEVAL_TOP_K` | `1000` / `150` / `6` | Chunking and retrieval |
| `BACKEND_URL` *(frontend)* | `http://127.0.0.1:8000` | Where the Next.js proxy forwards `/api` (runtime) |

## Database & migrations

| Table | Purpose |
|---|---|
| `courses` | Course metadata |
| `documents` | Uploaded files: type, size, SHA-256 (unique per course), status, error, page count, **embedding signature** |
| `chunks` | Text + `page_number` + `section` + `embedding vector(384)`; generated `content_tsv`; **HNSW** and **GIN** indexes |
| `chat_sessions`, `chat_messages` | Conversations; assistant messages store a source snapshot and generation metadata |
| `quizzes`, `quiz_questions`, `quiz_attempts` | Quizzes, answers (hidden from the client until graded), graded attempts |
| `flashcard_decks`, `flashcards` | Cards plus SM-2 state (`ease_factor`, `interval_days`, `repetitions`, `due_at`…) |

```bash
cd backend
alembic upgrade head          # also automatic on startup unless AUTO_MIGRATE=false
alembic downgrade base
```

> Switching to an embedding model with the **same** dimension is handled at runtime (documents are flagged and can be
> re-indexed in one click). A **different** dimension changes the `vector(n)` column type: start from a fresh database.

## API

Interactive docs: `/docs` on the backend. All 35 routes live under `/api`; the most important:

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status, DB dialect, active LLM / embedding providers and signature |
| GET · POST | `/courses` | List (with dashboard stats) · create |
| GET · PATCH · DELETE | `/courses/{id}` | Read · update · delete (cascades) |
| POST | `/demo` | Create (or return) the demo course from `sample_data/` |
| GET · POST | `/courses/{id}/documents` | List (with `needs_reindex`) · upload (multipart `files`, background processing) |
| POST | `/courses/{id}/reindex` | Re-index every document (e.g. after changing the embedding model) |
| GET · DELETE | `/documents/{id}` · GET `/documents/{id}/file` | Status · delete · original file (`#page=N` for PDFs) |
| GET | `/documents/{id}/chunks?page=` · `/chunks/{chunk_id}` | Inspect indexed chunks · one full passage |
| POST | `/courses/{id}/search` | Retrieval with per-retriever scores; `mode`: `hybrid` · `vector` · `keyword` |
| POST | `/courses/{id}/chat/stream` · `/courses/{id}/chat` | Ask — SSE (`meta`, `sources`, `token`…, `done` \| `error`) · single JSON |
| GET · DELETE | `/courses/{id}/chat/sessions` · `/chat/sessions/{sid}` | Sessions · transcript |
| POST · GET | `/courses/{id}/quizzes` · GET/DELETE `/quizzes/{qid}` | Generate · list · quiz without answers |
| POST · GET | `/quizzes/{qid}/attempts` | Submit & grade · attempt history |
| POST · GET | `/courses/{id}/decks` · GET/DELETE `/decks/{did}` · GET `/decks/{did}/study` | Flashcard decks · cards due now |
| POST | `/flashcards/{cid}/review` · `/decks/{did}/reset` | `{"rating": "again" \| "hard" \| "good" \| "easy"}` · reset progress |

```bash
curl -F "files=@sample_data/Lecture03_Gradient_Descent.pdf" http://localhost:3000/api/courses/$COURSE/documents
```

```bash
curl -N -X POST http://localhost:3000/api/courses/$COURSE/chat/stream -H "Content-Type: application/json" -d '{"question": "How should I choose a learning rate?"}'
```

Stream shape (abridged; values illustrative):

```text
event: sources
data: {"sources": [{"index": 1, "filename": "Lecture03_Gradient_Descent.pdf", "page_number": 3, "location": "page 3", "snippet": "If the learning rate is too large…", "vector_score": 0.79, "keyword_score": 5.31, …}], "low_confidence": false}

event: token
data: {"text": "Start "}

event: done
data: {"session_id": "…", "message_id": "…", "cited": [1, 2], "meta": {"provider": "anthropic", "model": "claude-opus-5-5", "latency_ms": 2140}}
```

Errors always look like `{"error": {"code": "index_outdated", "message": "...", "details": null}}` with a meaningful
status (`401 unauthorized`, `403 cross_origin`, `404`, `409 duplicate_document / no_materials / index_outdated`,
`413`, `415`, `422`, `502 llm_*`).

## Testing

```bash
cd backend
pytest                                    # 72 tests: SQLite, hashing embeddings, offline generator — no network
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/course_assistant_test pytest   # same tests on pgvector
pytest --cov=app                          # coverage (92% combined in CI)
python scripts/evaluate_retrieval.py      # retrieval benchmark (see evaluation/)
```

```bash
cd frontend
npm run lint && npm run typecheck && npm test && npm run build
```

End-to-end: with the stack running, `pip install playwright httpx` and
`python backend/scripts/capture_screenshots.py --web http://localhost:3000` drives your installed Edge/Chrome through
every feature (demo course, retrieval, streaming chat, passage viewer, quiz grading, flashcard review, mobile layout)
and refreshes `docs/screenshots/`.

CI runs both backend suites with a combined coverage gate (≥ 85%), the retrieval benchmark gate, frontend
lint/typecheck/tests/build, and builds both Docker images. What was and wasn't verified is recorded in
[`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## Deployment

- **Database:** managed PostgreSQL with pgvector — Neon, Supabase, AWS RDS / Aurora, Azure Flexible Server, Cloud SQL.
- **Backend:** the `backend/Dockerfile` image on Render, Fly.io, Railway, Cloud Run, ECS or a VM. Set `DATABASE_URL`,
  provider keys and `APP_API_TOKEN`; mount persistent storage for `UPLOAD_DIR` (or add object storage). Keep it on a
  private network — only the frontend needs to reach it. One worker per instance while ingestion runs in-process.
- **Frontend:** the `frontend/Dockerfile` standalone image (or Vercel) with `BACKEND_URL` and the same
  `APP_API_TOKEN` as runtime environment variables — no rebuild needed to point at another backend.
- **Hardening:** HTTPS in front of the frontend, user authentication (see roadmap), secrets in the platform's
  secret manager, log shipping.

## Known limitations

- **No user accounts yet.** `APP_API_TOKEN` stops the API being called around the frontend, but anyone who can open
  the frontend can see all courses. Don't expose it publicly without adding authentication.
- **No OCR.** Scanned PDFs are rejected with a clear message; images, charts and equations embedded as pictures are not
  understood.
- **Ingestion runs in the API process** (FastAPI `BackgroundTasks`); jobs interrupted by a restart are marked `failed`
  for retry. Large deployments should use a queue (Celery / RQ / Arq).
- The default embedding model is English-focused; for Chinese or mixed-language notes use the multilingual model above.
- **Short-answer grading** uses key-term recall against the model answer — transparent but less nuanced than an LLM
  grader. Chat follow-ups are retrieved with the latest question only (no query rewriting).
- **Offline mode** gives extractive answers and heuristic quizzes/cards for trying the app without keys; quality is far
  below LLM generation. The Claude / OpenAI-compatible adapters are tested with fake SDK clients only — see
  [`docs/VERIFICATION.md`](docs/VERIFICATION.md) for everything that has and hasn't been run.
- The retrieval benchmark is small (23 chunks, 33 developer-written questions).
- `npm audit` reports advisories only in the dev-time ESLint toolchain (`braces` via `eslint-config-next`); production
  dependencies audit clean.

## Roadmap

- Authentication and per-user courses; shared class spaces
- OCR for scanned PDFs, figure understanding, lecture-recording transcripts
- Query rewriting for follow-up questions, cross-encoder re-ranking; a larger benchmark with student-written
  questions and answer-faithfulness scoring once an LLM is configured
- LLM-based short-answer grading with rubrics; adaptive quizzes that target weak concepts
- FSRS scheduling; study streaks and analytics
- Task queue for ingestion; S3-compatible file storage; per-request cost and token tracking
- Chinese / multilingual UI

## Resume / CV description

**AI Course Assistant** — full-stack retrieval-augmented study assistant · Python, FastAPI, PostgreSQL/pgvector,
Next.js, TypeScript, Docker

- Built a full-stack RAG app that turns students' lecture PDFs, slide decks and notes into **page- and slide-cited**
  answers streamed over SSE, auto-generated quizzes with grading, and SM-2 spaced-repetition flashcards.
- Designed **hybrid retrieval** — pgvector HNSW search plus BM25 computed on PostgreSQL's GIN-indexed full-text
  vectors, fused with Reciprocal Rank Fusion — and evaluated it on a 33-question labelled benchmark: hybrid reached
  **Recall@5 1.00 and MRR 0.92**, outperforming vector-only (MRR 0.83), with **5/5** off-topic questions flagged and
  0 false alarms; the ablation exposed and fixed an IDF-less ranking bug (keyword Recall@1 0.64 → 0.86).
- Made answers verifiable and safe: server-side citation validation with source snapshots, a viewer for the exact
  retrieved passage, a prompt-injection guard, low-confidence refusal, and embedding-model versioning that prevents
  mixing vector spaces.
- Abstracted LLM providers behind a task-level interface (Claude via the Anthropic SDK with structured outputs, any
  OpenAI-compatible API, and a deterministic offline mode) with validation and repair of generated content.
- Shipped with **72 backend tests on SQLite and PostgreSQL (92% coverage)**, frontend unit tests, a Playwright
  end-to-end suite including mobile layout checks, a same-origin Next.js API proxy with CSRF protection, Docker
  Compose, Alembic migrations and GitHub Actions CI with coverage and retrieval-quality gates.

<details>
<summary>中文版（简历要点）</summary>

**AI Course Assistant（AI 课程助手）** — 全栈检索增强（RAG）学习助手 · Python、FastAPI、PostgreSQL/pgvector、Next.js、TypeScript、Docker

- 独立实现全栈 RAG 学习应用：将课件 PDF、PPT 与笔记转化为**精确到页码/幻灯片引用**的 SSE 流式问答、可自动判分的测验，以及基于 SM-2 间隔重复的闪卡复习。
- 设计**混合检索**：pgvector HNSW 语义检索 + 基于 PostgreSQL GIN 全文索引计算的 BM25，经 RRF 融合；在 33 题人工标注评测集上混合检索 **Recall@5 达 1.00、MRR 0.92**，优于纯向量检索（MRR 0.83），5/5 个超纲问题被识别、零误报；消融实验发现并修复了缺少 IDF 的排序缺陷（关键词 Recall@1 0.64 → 0.86）。
- 保证回答可核查、可控：服务端引用校验与来源快照、原文段落查看、提示注入防护、低置信度拒答，以及防止混用不同向量空间的 embedding 版本管理。
- 以任务级接口抽象 LLM 提供方（Anthropic SDK 结构化输出调用 Claude、任意 OpenAI 兼容接口、确定性离线模式），对生成内容进行校验与修复。
- 工程化交付：**72 个后端测试同时在 SQLite 与 PostgreSQL 上运行（覆盖率 92%）**、前端单元测试、含移动端检查的 Playwright 端到端测试、带 CSRF 防护的 Next.js 同源代理、Docker Compose、Alembic 迁移，以及带覆盖率与检索质量门槛的 GitHub Actions CI。

</details>

## License

[MIT](LICENSE)
