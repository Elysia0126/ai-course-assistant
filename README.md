# AI Course Assistant

**Upload your lecture slides, PDFs and notes — then ask questions with page-level citations, generate quizzes, and
study flashcards on a spaced-repetition schedule. Everything is grounded in *your* course materials.**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.142-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

![Ask a question and get an answer that cites the exact slide and page](docs/screenshots/chat.png)

> The screenshots show the built-in **offline mode** (no API key configured), where answers are extracted
> sentences. With `ANTHROPIC_API_KEY` (or any OpenAI-compatible provider) set, the same UI streams generated,
> cited explanations — nothing else changes.

---

## Contents

- [Features](#features) · [Screenshots](#screenshots) · [Architecture](#architecture) · [Tech stack](#tech-stack)
- [Design decisions](#key-design-decisions) · [Project structure](#project-structure)
- [Quick start (Docker)](#quick-start-with-docker) · [Local development](#local-development)
- [Configuration](#configuration) · [Database & migrations](#database--migrations) · [API](#api)
- [Testing](#testing) · [Deployment](#deployment) · [Known limitations](#known-limitations) · [Roadmap](#roadmap)
- [Resume / CV description](#resume--cv-description)

## Features

| | |
|---|---|
| 📚 **Course & material management** | Create courses; upload **PDF, PowerPoint (.pptx), Word (.docx), Markdown, TXT** (drag & drop, multi-file, progress bar). Content sniffing, size limits and per-course de-duplication (SHA-256). |
| 🧩 **Location-aware parsing & chunking** | PDFs are parsed page by page, slides slide by slide (including **speaker notes and tables**), Markdown/Word by heading. Chunks never cross a page boundary, so every citation is exact. |
| 🔎 **Hybrid retrieval** | **pgvector HNSW** cosine search + **PostgreSQL full-text search**, fused with **Reciprocal Rank Fusion**. A built-in *retrieval inspector* shows vector, keyword and fused scores for any query. |
| 💬 **Cited Q&A (RAG)** | Answers stream token-by-token over **Server-Sent Events**, cite sources inline as `[1]`, `[2]`; clicking a citation highlights the passage and **opens the PDF at the cited page**. Off-topic questions are flagged as low-confidence. Chats are saved as multi-turn sessions. |
| 📝 **Quiz generator** | Multiple-choice, true/false and short-answer questions at three difficulty levels, optionally focused on a topic or specific documents. Answers are hidden until submission; grading returns explanations and the source page for every question. |
| 🃏 **Flashcards with spaced repetition** | Generated decks reviewed with the **SM-2** algorithm (Again / Hard / Good / Easy, with next-interval preview and keyboard shortcuts). |
| 🔌 **Pluggable providers** | LLM: **Claude** (Anthropic SDK, streaming, structured outputs), any **OpenAI-compatible** API (OpenAI, DeepSeek, Qwen, Ollama, vLLM…), or a deterministic **offline** mode. Embeddings: local **fastembed** (ONNX, free), OpenAI-compatible, or hashing (tests). |
| 🛡️ **Robustness** | Background ingestion with a `pending → processing → ready / failed` state machine, retry, crash recovery, a consistent JSON error model, and validated LLM output. |

## Screenshots

| Course dashboard | Materials + retrieval inspector |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Materials](docs/screenshots/materials.png) |
| **Quiz with grading & sources** | **Flashcard study (SM-2)** |
| ![Quiz](docs/screenshots/quiz.png) | ![Flashcards](docs/screenshots/flashcards.png) |

All screenshots are produced by an automated end-to-end walkthrough (`backend/scripts/capture_screenshots.py`).

## Architecture

```mermaid
flowchart LR
    subgraph Browser["Next.js 16 frontend"]
        UI["Dashboard · Materials · Ask · Quiz · Flashcards"]
    end

    subgraph API["FastAPI backend"]
        Routes["REST + SSE routes"]
        Ingest["Ingestion pipeline<br/>parse → chunk → embed"]
        Retriever["Hybrid retriever<br/>vector + keyword → RRF"]
        Gen["Generation backends<br/>Claude · OpenAI-compatible · offline"]
        Study["Quiz grading · SM-2 scheduler"]
    end

    subgraph Data["PostgreSQL 17 + pgvector"]
        Tables[("courses · documents · chunks<br/>chats · quizzes · flashcards")]
        HNSW[["HNSW index (cosine)"]]
        GIN[["GIN index (tsvector)"]]
    end

    Files[("Upload storage")]
    Embed["Embeddings<br/>fastembed (local ONNX) / OpenAI"]
    LLM["LLM API"]

    UI -- "JSON / multipart / SSE" --> Routes
    Routes --> Ingest & Retriever & Study
    Ingest --> Files
    Ingest --> Embed
    Ingest --> Tables
    Retriever --> HNSW & GIN
    Retriever --> Gen
    Gen --> LLM
    Study --> Tables
```

**Ingestion** — `POST /documents` validates and stores the file, returns immediately (`201`), and a background task
parses it into location-tagged sections, splits them into chunks, embeds each chunk with a *contextual header*
(`document title — section`) and swaps the new chunks in atomically while marking the document `ready`.

**Question answering**

```mermaid
sequenceDiagram
    participant UI as Browser
    participant API as FastAPI
    participant DB as Postgres (pgvector + FTS)
    participant LLM as LLM provider
    UI->>API: POST /courses/{id}/chat/stream {question, session_id?, document_ids?}
    API->>DB: save user message (new session if needed)
    API-->>UI: event: meta
    API->>DB: top-30 by cosine (HNSW) ∥ top-30 by ts_rank_cd
    API->>API: Reciprocal Rank Fusion → top-k chunks
    API-->>UI: event: sources (file, page/slide, snippet, scores, low_confidence)
    API->>LLM: system prompt + numbered <source> blocks + history
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
| Frontend | Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind CSS 4, react-markdown + KaTeX, lucide icons, sonner |
| Backend | Python 3.12, FastAPI, Pydantic v2 / pydantic-settings, SQLAlchemy 2, Alembic, Uvicorn |
| Data | PostgreSQL 17 + **pgvector** (HNSW, cosine), PostgreSQL full-text search (`tsvector` + GIN); SQLite fallback for tests |
| Parsing | pypdf, python-pptx, python-docx, Markdown/TXT parsers with encoding detection |
| AI | Anthropic Python SDK (Claude, streaming, structured outputs), OpenAI SDK (any compatible endpoint), fastembed (BAAI/bge-small-en-v1.5, ONNX) |
| Quality | pytest (58 tests, run on SQLite **and** pgvector), Vitest + Testing Library, Playwright E2E walkthrough, Ruff, ESLint, `tsc` |
| Ops | Docker (non-root images, health checks), docker compose, GitHub Actions CI |

## Key design decisions

- **Citations you can trust.** Chunks never span pages/slides, each stores `page_number` + `section`, and the model
  sees numbered `<source id="n" file=… location="page 4">` blocks. After generation the backend keeps only
  citation numbers that refer to retrieved sources, and stores a **snapshot** of each source with the message, so
  old answers keep working even after a document is re-indexed.
- **Hybrid retrieval with RRF.** Dense vectors handle paraphrases ("how do I pick a step size" → *learning rate*);
  keyword search handles exact jargon and symbols ("Adam", "L2"). Reciprocal Rank Fusion merges the two rankings
  without calibrating their incompatible score scales. Keyword queries use OR-semantics with coverage-aware
  `ts_rank_cd`, because questions rarely contain *every* term of the answer passage.
- **Contextual chunk headers.** Each chunk is embedded as `"<document title> — <section>\n<text>"`, which helps short
  slide bullets retrieve well.
- **Low-confidence detection.** If the best cosine similarity is below a per-model threshold, the UI warns that the
  materials may not cover the question (e.g. *"Who won the 1998 World Cup?"* in an ML course).
- **Provider-agnostic generation at the *task* level.** Backends implement `stream_answer`, `generate_quiz` and
  `generate_flashcards`. Claude uses the official SDK with streaming, adaptive thinking/effort, refusal handling and
  server-side fallbacks, and Pydantic **structured outputs** for quizzes/cards; OpenAI-compatible providers use JSON
  mode with validation and automatic repair retries. An **offline backend** implements the same contract with
  extractive heuristics — so the app, the demo and the whole test suite run without any API key.
- **Never trust model output blindly.** Generated questions are validated and repaired (MCQ answer must be one of
  the options; options are shuffled to remove position bias; true/false normalised; duplicates and invalid
  `source_id`s dropped).
- **Portable persistence.** A custom `EmbeddingVector` SQLAlchemy type maps to `vector(384)` on PostgreSQL and JSON
  elsewhere; the retriever uses SQL (HNSW + FTS) on Postgres and numpy + an in-process **BM25** elsewhere. One
  Alembic migration covers both dialects, and the same tests run against each.
- **Operational details.** Interrupted ingestion jobs are marked `failed` on startup so users can retry; uploads are
  sniffed (`%PDF`, ZIP magic) before parsing; every error has the shape `{"error": {"code", "message", "details"}}`.

## Project structure

```
ai-course-assistant/
├── backend/
│   ├── app/
│   │   ├── api/routes/        # courses, documents, chat (+SSE, search), quizzes, flashcards, health
│   │   ├── core/              # settings, error model + handlers, logging
│   │   ├── db/                # engine/session, cross-dialect types (EmbeddingVector, UTCDateTime)
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── parsing.py     # PDF / PPTX / DOCX / MD / TXT → location-tagged sections
│   │   │   ├── chunking.py    # structure-aware splitter with overlap
│   │   │   ├── embeddings.py  # fastembed · OpenAI · hashing providers
│   │   │   ├── ingestion.py   # background pipeline + status state machine
│   │   │   ├── retrieval.py   # pgvector + FTS / numpy + BM25, RRF, study-chunk sampler
│   │   │   ├── chat.py        # RAG orchestration, citation validation, sessions
│   │   │   ├── quizzes.py     # generation, validation/repair, grading
│   │   │   ├── flashcards.py  # deck generation, reviews
│   │   │   ├── srs.py         # SM-2 scheduler
│   │   │   └── llm/           # prompts, Claude / OpenAI-compatible / offline backends
│   │   └── main.py            # app factory (lifespan, CORS, request IDs, routers)
│   ├── alembic/               # migrations (pgvector extension, HNSW + GIN indexes)
│   ├── scripts/               # dev_db.py · seed_demo.py · make_sample_data.py · capture_screenshots.py
│   ├── tests/                 # 58 pytest tests (SQLite + optional PostgreSQL)
│   ├── Dockerfile
│   └── requirements*.txt
├── frontend/
│   ├── src/app/               # / (dashboard) and /courses/[courseId]/{materials,ask,quiz,flashcards}
│   ├── src/components/        # UI kit, Markdown + citation chips, source cards, scope picker…
│   ├── src/lib/               # typed API client, SSE parser, citation + SM-2 helpers (+ tests)
│   └── Dockerfile
├── sample_data/               # demo course: 6-page PDF lecture, 8-slide PPTX with notes, Markdown guide
├── docs/screenshots/
├── docker-compose.yml
├── .env.example
└── .github/workflows/ci.yml
```

## Quick start with Docker

Requirements: Docker with Compose v2.24+.

```bash
cp .env.example .env          # optional: add ANTHROPIC_API_KEY (or an OpenAI-compatible provider)
docker compose up --build
```

- Frontend: <http://localhost:3000> · API docs (Swagger): <http://localhost:8000/docs>
- Load the demo course (needs Python + `httpx` on the host, or use the UI to upload `sample_data/*`):

```bash
python backend/scripts/seed_demo.py --api http://localhost:8000
```

The backend image bakes in the local embedding model, runs `alembic upgrade head` on start, and stores uploads in
a named volume; Postgres data lives in the `pgdata` volume.

## Local development

Requirements: **Python 3.11+** (3.12 recommended), **Node.js 20.9+**, and PostgreSQL with pgvector (any of the
three options below).

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp ../.env.example .env            # then edit DATABASE_URL / API keys
```

Pick a database:

| Option | How | Notes |
|---|---|---|
| **Docker pgvector** (recommended) | `docker compose up -d db` | Matches production; `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/course_assistant` |
| **Embedded Postgres, no Docker** | `python scripts/dev_db.py --write-env` | Runs PostgreSQL 16 + pgvector from a pip package (`pgserver`, Python ≤ 3.12) and writes `DATABASE_URL` into `backend/.env` |
| **SQLite** (quick look) | `DATABASE_URL=sqlite:///./data/dev.db` | No pgvector/FTS — uses the in-process numpy + BM25 retriever |

```bash
uvicorn app.main:app --reload            # http://localhost:8000/docs — migrations run automatically
python scripts/seed_demo.py              # optional: demo course from ../sample_data
```

The first run downloads the ~65 MB embedding model (`BAAI/bge-small-en-v1.5`, ONNX) into `backend/data/models`.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local               # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                              # http://localhost:3000
```

## Configuration

All settings are environment variables (or `.env` / `backend/.env`); see [`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/course_assistant` | SQLAlchemy URL (PostgreSQL + pgvector, or SQLite) |
| `AUTO_MIGRATE` | `true` | Run Alembic migrations on startup |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed browser origins |
| `MAX_UPLOAD_MB` | `25` | Per-file upload limit |
| `UPLOAD_DIR` | `backend/data/uploads` | Where original files are stored |
| `LLM_PROVIDER` | `auto` | `auto` · `anthropic` · `openai` · `offline` (`auto` picks Anthropic → OpenAI-compatible → offline based on which keys exist) |
| `ANTHROPIC_API_KEY` | — | Enables Claude |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Any Claude model id |
| `ANTHROPIC_EFFORT` | `medium` | `low`…`max`; leave blank for models without effort support |
| `ANTHROPIC_FALLBACKS` | `true` | Server-side refusal fallback to Anthropic's recommended model |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | — | Any OpenAI-compatible chat endpoint (e.g. DeepSeek `https://api.deepseek.com/v1` + `deepseek-chat`, Ollama `http://localhost:11434/v1`) |
| `EMBEDDING_PROVIDER` | `fastembed` | `fastembed` (local) · `openai` · `hash` (tests) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | For Chinese/multilingual material: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `EMBEDDING_DIM` | `384` | Must match the model; part of the schema (see below) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `150` | Characters per chunk / overlap |
| `RETRIEVAL_TOP_K` | `6` | Passages given to the model per question |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend → API base URL (inlined at build time) |

## Database & migrations

| Table | Purpose |
|---|---|
| `courses` | Course metadata (name, code, term, color) |
| `documents` | Uploaded files: type, size, SHA-256, status, error, page count |
| `chunks` | Text + `page_number` + `section` + `embedding vector(384)`; generated `content_tsv tsvector`; **HNSW** and **GIN** indexes |
| `chat_sessions`, `chat_messages` | Conversations; assistant messages store a source snapshot and generation metadata |
| `quizzes`, `quiz_questions`, `quiz_attempts` | Generated quizzes, answers (hidden from the client until graded), graded attempts |
| `flashcard_decks`, `flashcards` | Cards plus SM-2 state (`ease_factor`, `interval_days`, `repetitions`, `due_at`…) |

```bash
cd backend
alembic upgrade head          # also runs automatically on startup unless AUTO_MIGRATE=false
alembic downgrade base        # drop everything
alembic revision -m "..."     # new migration
```

> Changing `EMBEDDING_DIM` changes the `vector(n)` column type: start from a fresh database (or write a migration)
> and re-process documents.

## API

Interactive docs: `http://localhost:8000/docs`. All routes are under `/api`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status, DB dialect, active LLM / embedding providers |
| GET · POST | `/courses` | List (with dashboard stats) · create |
| GET · PATCH · DELETE | `/courses/{id}` | Read · update · delete (cascades to everything) |
| GET · POST | `/courses/{id}/documents` | List · upload (multipart `files`, processed in the background) |
| GET · DELETE | `/documents/{id}` | Status · delete |
| GET | `/documents/{id}/file` | Original file (inline; append `#page=N` for PDFs) |
| GET | `/documents/{id}/chunks?page=` | Inspect indexed chunks |
| POST | `/documents/{id}/reprocess` | Re-run ingestion |
| POST | `/courses/{id}/search` | Hybrid search with per-retriever scores |
| POST | `/courses/{id}/chat/stream` | Ask — Server-Sent Events: `meta`, `sources`, `token`…, `done` \| `error` |
| POST | `/courses/{id}/chat` | Ask — single JSON response |
| GET | `/courses/{id}/chat/sessions` · `/chat/sessions/{sid}` | Sessions · transcript (DELETE to remove) |
| POST · GET | `/courses/{id}/quizzes` | Generate · list |
| GET · DELETE | `/quizzes/{qid}` | Quiz without answers · delete |
| POST · GET | `/quizzes/{qid}/attempts` | Submit & grade · attempt history |
| POST · GET | `/courses/{id}/decks` | Generate · list flashcard decks |
| GET · DELETE | `/decks/{did}` | Deck with cards · delete |
| GET | `/decks/{did}/study` | Cards due now |
| POST | `/flashcards/{cid}/review` | `{"rating": "again" \| "hard" \| "good" \| "easy"}` |
| POST | `/decks/{did}/reset` | Reset review progress |

Examples:

```bash
curl -F "files=@sample_data/Lecture03_Gradient_Descent.pdf" http://localhost:8000/api/courses/$COURSE/documents
```

```bash
curl -N -X POST http://localhost:8000/api/courses/$COURSE/chat/stream -H "Content-Type: application/json" -d '{"question": "How should I choose a learning rate?"}'
```

Stream shape (abridged; values illustrative):

```text
event: sources
data: {"sources": [{"index": 1, "filename": "Lecture03_Gradient_Descent.pdf", "page_number": 3, "location": "page 3", "snippet": "If the learning rate is too large…", "vector_score": 0.79, "keyword_score": 0.31, …}], "low_confidence": false}

event: token
data: {"text": "Start "}

event: done
data: {"session_id": "…", "message_id": "…", "cited": [1, 2], "meta": {"provider": "anthropic", "model": "claude-opus-5-5", "latency_ms": 2140}}
```

```bash
curl -X POST http://localhost:8000/api/courses/$COURSE/quizzes -H "Content-Type: application/json" -d '{"num_questions": 5, "difficulty": "medium", "question_types": ["mcq", "true_false"], "topic": "learning rate"}'
```

Errors always look like `{"error": {"code": "unsupported_file_type", "message": "...", "details": null}}` with a
meaningful status (`404`, `409 duplicate_document / no_materials`, `413`, `415`, `422`, `502 llm_*`).

## Testing

```bash
cd backend
pytest                                   # 58 tests: SQLite, hashing embeddings, offline generator — no network
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/course_assistant_test pytest
ruff check . && ruff format --check .
```

The second run exercises the production paths (pgvector HNSW, `tsvector` search, JSONB). Coverage includes parsers
(page/slide/heading locations, scanned/corrupt files), chunking invariants, BM25/RRF/embeddings, every API route
and error case, SSE event ordering, citation validation, quiz grading, SM-2 scheduling, provider adapters
(Claude and OpenAI-compatible, tested against fake SDK clients), config parsing, and migration up/down.

```bash
cd frontend
npm run lint && npm run typecheck && npm test && npm run build
```

End-to-end: with the stack running, `pip install playwright` and
`python backend/scripts/capture_screenshots.py --web http://localhost:3000 --api http://localhost:8000` drives a
real browser (your installed Edge/Chrome) through every feature and refreshes `docs/screenshots/`.

CI (`.github/workflows/ci.yml`) runs the backend suite on SQLite **and** a pgvector service container, the frontend
lint/typecheck/tests/build, and builds both Docker images.

## Deployment

The app is three stateless-ish pieces plus storage, so most platforms work:

- **Database:** any managed PostgreSQL with pgvector — Neon, Supabase, AWS RDS / Aurora, Azure Flexible Server,
  Google Cloud SQL. Run `alembic upgrade head` once (the Docker image does this on start).
- **Backend:** the `backend/Dockerfile` image on Render, Fly.io, Railway, Cloud Run, ECS or a VM. Set
  `DATABASE_URL`, `CORS_ORIGINS=https://your-frontend`, provider keys, and mount persistent storage for
  `UPLOAD_DIR` (or swap in S3-compatible storage — see roadmap). Keep a single worker process per instance while
  ingestion runs in-process.
- **Frontend:** Vercel (zero config) or the `frontend/Dockerfile` standalone image. Set `NEXT_PUBLIC_API_URL` at
  **build** time to the public API URL.
- **Production hardening:** put the API behind HTTPS, add authentication (see roadmap), keep secrets in the
  platform's secret manager, and configure log shipping.

## Known limitations

- **No authentication / multi-tenancy yet** — it is a single-user study tool; anyone with the URL can see all
  courses. Don't expose it publicly without adding auth.
- **Scanned PDFs** (images only) are rejected with a clear message; there is no OCR. Images, charts and equations
  embedded as pictures are not understood.
- **Background jobs run in the API process** (FastAPI `BackgroundTasks`). Fine for personal use; large deployments
  should move ingestion to a queue (Celery / RQ / Arq) — jobs interrupted by a restart are marked `failed` for retry.
- **Embedding dimension is fixed in the schema** (`vector(384)`); switching to a model with another dimension needs
  a fresh database or a migration plus re-indexing.
- The default embedding model is English-focused; for Chinese or mixed-language notes switch to the multilingual
  model listed under [Configuration](#configuration).
- **Short-answer grading** uses key-term recall against the model answer — transparent and deterministic, but less
  nuanced than an LLM grader.
- **Offline mode** produces extractive answers and heuristic quizzes/cards; quality is far below LLM generation and is
  meant for trying the app without keys and for tests. The Claude and OpenAI-compatible adapters are unit-tested with
  fake SDK clients; validate them with your own key before relying on them.
- Upload files live on local disk (or a Docker volume), not object storage.
- `npm audit` reports advisories in the **dev-only** ESLint toolchain (`braces` via `eslint-config-next`); production
  dependencies audit clean.

## Roadmap

- Authentication (OAuth / email) and per-user courses; shared class spaces for study groups
- OCR for scanned PDFs, image/figure understanding, YouTube/lecture-recording transcripts
- Cross-encoder re-ranking and query rewriting for follow-up questions; an evaluation set (retrieval recall@k,
  answer faithfulness) to tune chunking and retrieval
- LLM-based short-answer grading with rubrics; adaptive quizzes that target weak concepts
- FSRS scheduling and Anki (`.apkg`) export; study streaks and analytics
- Task queue for ingestion; S3-compatible file storage; per-request cost and token tracking
- Chinese / multilingual UI

## Resume / CV description

**AI Course Assistant** — full-stack retrieval-augmented study assistant · Python, FastAPI, PostgreSQL/pgvector,
Next.js, TypeScript, Docker

- Built a full-stack RAG app that lets students upload lecture PDFs, slide decks and notes, then ask questions
  answered with **page- and slide-level citations**, auto-generated quizzes and spaced-repetition flashcards.
- Designed a **hybrid retrieval** pipeline: pgvector **HNSW** semantic search plus PostgreSQL **full-text** search
  fused with **Reciprocal Rank Fusion**, structure-aware chunking that never crosses page boundaries, contextual chunk
  headers, and low-confidence detection for off-topic questions.
- Implemented token-level **streaming answers over Server-Sent Events** with inline citation chips that deep-link to
  the cited PDF page; citations are validated server-side and snapshotted with each message.
- Abstracted LLM providers behind a task-level interface (Claude via the Anthropic SDK with structured outputs,
  any OpenAI-compatible API, and a deterministic offline mode), with schema validation and repair of generated
  quiz/flashcard content.
- Implemented SM-2 spaced repetition, server-side quiz grading, a background ingestion state machine with recovery,
  and a consistent error model across 30+ REST endpoints.
- Wrote **58 backend tests** run against both SQLite and PostgreSQL+pgvector, frontend unit/component tests, and a
  Playwright end-to-end walkthrough; shipped with Docker Compose, Alembic migrations and GitHub Actions CI.

<details>
<summary>中文版（简历要点）</summary>

**AI Course Assistant（AI 课程助手）** — 全栈检索增强（RAG）学习助手 · Python、FastAPI、PostgreSQL/pgvector、Next.js、TypeScript、Docker

- 独立设计并实现全栈 RAG 应用：学生上传课件 PDF、PPT 和笔记后，可获得**精确到页码/幻灯片**的引用式问答、自动生成的测验，以及基于间隔重复的闪卡复习。
- 设计**混合检索**管线：pgvector **HNSW** 语义检索 + PostgreSQL **全文检索**，用 **RRF（倒数排名融合）**合并结果；结构感知分块保证不跨页，并加入上下文块标题和低置信度（超出资料范围）检测。
- 基于 **SSE** 实现逐 token 流式回答，引用角标可直接跳转到 PDF 对应页；引用在服务端校验，并随消息保存来源快照。
- 以任务级接口抽象 LLM 提供方（Anthropic SDK 调用 Claude 并使用结构化输出、任意 OpenAI 兼容接口、确定性离线模式），对生成的题目和闪卡做 schema 校验与自动修复。
- 实现 SM-2 间隔重复算法、服务端判分、带故障恢复的后台入库状态机，以及覆盖 30+ 个 REST 接口的统一错误模型。
- 编写 **58 个后端测试**（同时在 SQLite 和 PostgreSQL+pgvector 上运行）、前端单元/组件测试和 Playwright 端到端测试；提供 Docker Compose、Alembic 迁移和 GitHub Actions CI。

</details>

## License

[MIT](LICENSE)
