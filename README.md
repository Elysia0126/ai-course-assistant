# AI Course Assistant

**Upload your lecture slides, PDFs and notes — then ask questions with page-level citations, generate quizzes, and
study flashcards on a spaced-repetition schedule. Everything is grounded in *your* course materials.**

[![CI](https://github.com/Elysia0126/ai-course-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/Elysia0126/ai-course-assistant/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.142-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![Coverage](https://img.shields.io/badge/coverage-93%25-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

![Ask a question and get an answer that cites the exact slide and page](docs/screenshots/chat.png)

> The screenshots show the built-in **offline mode** (no API key configured), where answers are extracted
> sentences. With `ANTHROPIC_API_KEY` (or any OpenAI-compatible provider) set, the same UI streams generated,
> cited explanations — nothing else changes.

---

## Contents

- [Features](#features) · [Screenshots](#screenshots) · [Retrieval quality](#retrieval-quality) · [Architecture](#architecture)
- [Accounts & security](#accounts--security) · [Tech stack](#tech-stack) · [Design decisions](#key-design-decisions)
- [Project structure](#project-structure) · [Quick start (Docker)](#quick-start-with-docker) · [Local development](#local-development)
- [Configuration](#configuration) · [Database & migrations](#database--migrations) · [API](#api)
- [Testing](#testing) · [Deployment](#deployment) · [Troubleshooting](#troubleshooting) · [Known limitations](#known-limitations)
- [Roadmap](#roadmap) · [Resume / CV description](#resume--cv-description)

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
| 🔐 **Accounts & private data** | Email + password sign-up/sign-in (**Argon2id**), **server-side sessions** in an HttpOnly cookie (only a SHA-256 of the token is stored), *Remember me*, idle + absolute expiry, sign-out that revokes the session. **Password reset by email** (single-use, 30-minute tokens; SMTP). Every course — and everything in it — belongs to one user; other users get `404`. CSRF tokens + strict Origin checks, database-backed rate limits, a minimal **admin** view, and a CLI for admins and legacy data. |
| 🛡️ **Safety & robustness** | Prompt-injection guard (retrieved text is data, not instructions); **index versioning** (vectors from a different embedding model are never mixed — one-click re-index); background ingestion state machine with crash recovery; same-origin API proxy with a service token between proxy and API; private `no-store` responses; consistent JSON errors. |

## Screenshots

| Course dashboard | Materials + retrieval inspector |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Materials](docs/screenshots/materials.png) |
| **Exact retrieved passage behind a citation** | **Quiz with grading & sources** |
| ![Passage viewer](docs/screenshots/passage.png) | ![Quiz](docs/screenshots/quiz.png) |
| **Flashcard study (SM-2)** | **Mobile (390 px)** |
| ![Flashcards](docs/screenshots/flashcards.png) | <img src="docs/screenshots/mobile.png" alt="Mobile layout" width="260"> |
| **Sign in** (private pages redirect here) | **Create an account** |
| ![Sign in](docs/screenshots/login.png) | ![Sign up](docs/screenshots/register.png) |
| **New password from the emailed reset link** | **Sign-in on mobile** |
| ![Reset password](docs/screenshots/reset-password.png) | <img src="docs/screenshots/mobile-login.png" alt="Mobile sign-in" width="260"> |

All screenshots come from an automated end-to-end run in a real browser (`backend/scripts/capture_screenshots.py`),
which signs up a fresh account, uses every feature, signs out and resets the password through a real SMTP server.

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
        Pages["/login · /register · /forgot-password · /reset-password<br/>Dashboard · Materials · Ask · Quiz · Flashcards · Admin"]
        Guard["proxy.ts (redirect hint)<br/>(app) layout: session check"]
        Proxy["/api proxy<br/>(streams, auth cookies both ways,<br/>service token, no-store)"]
    end

    subgraph API["FastAPI backend"]
        Auth["Auth: sessions · CSRF · rate limits<br/>CurrentUser + ownership checks"]
        Routes["REST + SSE routes"]
        Ingest["Ingestion<br/>parse → chunk → embed"]
        Retriever["Hybrid retriever<br/>HNSW + BM25 → RRF"]
        Gen["Generation<br/>Claude · OpenAI-compatible · offline"]
        Study["Quiz grading · SM-2"]
    end

    subgraph Data["PostgreSQL + pgvector"]
        Accounts[("users · auth_sessions<br/>password_reset_tokens · rate_limit_counters")]
        Tables[("courses (owner_id) · documents · chunks<br/>chats · quizzes · flashcards")]
        HNSW[["HNSW index (cosine)"]]
        GIN[["GIN index (tsvector)"]]
    end

    Files[("Upload storage")]
    Embed["Embeddings<br/>fastembed (local ONNX) / OpenAI"]
    LLM["LLM API"]
    SMTP["SMTP"]

    Pages --> Guard
    Guard -- "GET /api/auth/me" --> Auth
    Pages --> Proxy
    Proxy -- "JSON / multipart / SSE<br/>+ session cookie" --> Auth
    Auth --> Accounts
    Auth --> Routes
    Auth -- "reset link" --> SMTP
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
(`BACKEND_URL`, a runtime setting), forwards only the auth cookies and CSRF header, adds `APP_API_TOKEN` server-side
and passes each `Set-Cookie` back separately. FastAPI makes every authentication and authorisation decision.

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

## Accounts & security

**Who decides.** FastAPI owns identity and authorisation; Next.js renders pages and proxies requests. Nothing about a
user is trusted from the browser except the session cookie, which the API looks up on every request.

| Concern | Implementation |
|---|---|
| Passwords | **Argon2id** via `pwdlib`; NFKC-normalised, never trimmed or truncated; 15–128 characters, any Unicode, no composition rules (NIST 800-63B style); confirmation checked server-side |
| Sessions | 256-bit random token in an **HttpOnly, SameSite=Lax, Path=/, host-only** cookie (`Secure` + `__Host-` prefix behind HTTPS). The database keeps only its **SHA-256** (`auth_sessions.token_hash`). Every sign-in creates a new session (no fixation) and revokes the browser's previous one |
| Lifetime | 12 h, or 30 days with *Remember me*; 7-day idle timeout; `revoked_at`; cookie `Max-Age` equals the database expiry. Disabled users and revoked/expired/idle sessions get `401` and the stale cookie is cleared. Sessions survive API restarts |
| CSRF | Every `POST/PUT/PATCH/DELETE` needs (1) an `Origin` (or `Referer`) equal to a trusted origin — scheme, host and port; missing ⇒ refused — and (2) `X-CSRF-Token`: for a session, an HMAC derived from the session secret; before sign-in, a double-submit value bound to an HttpOnly cookie. The proxy's same-host check is only an early filter |
| Data ownership | `courses.owner_id` is set from the session, never from the request. Documents, chunks, chats, quizzes, attempts, decks and cards inherit ownership through their course: every lookup by id joins up to the course and filters on the owner, so other users' ids answer `404` — exactly like ids that don't exist. Nested ids (`document_ids`, `session_id`, question ids) must belong to the same course/quiz. Streaming chat and background ingestion re-check ownership in their own database sessions |
| Rate limits | Fixed windows stored in the database (work across processes): sign-in per IP and per normalised email (failures only), sign-up per IP, reset requests per IP and per email, reset submissions per IP — `429` + `Retry-After`. `X-Forwarded-For` is only believed from the proxy (proved by `APP_API_TOKEN`) or `TRUSTED_PROXY_IPS` |
| Password reset | Same `202` answer for known and unknown emails, mail sent after the response. Single-use 256-bit token, only its hash stored, 30-minute expiry, older tokens invalidated; consumed with a conditional `UPDATE` so concurrent submissions succeed once. Success revokes **every** session and doesn't sign in. The link is `APP_PUBLIC_URL/reset-password#token=…` (fragment: never sent to a server or in a `Referer`); the page is `no-referrer` and strips the token from the address bar |
| Roles | `user` (default, also for the first account) and `admin`. Admins are created/promoted only with the CLI; the admin API lists accounts and enables/disables them (disabling revokes all sessions; the last active admin can't be removed). Admins still see only their own courses |
| Production guard | `APP_ENV=production` refuses to start with an `http://` `APP_PUBLIC_URL`, insecure cookies, a missing/short `APP_API_TOKEN`, or the dev outbox mailer |
| Secrets in logs | Passwords, cookies, `Authorization`, session and reset tokens are never logged (asserted by a test) |

**Public API routes:** `GET /api/health`, `GET /api/auth/csrf`, `POST /api/auth/register · login · logout ·
forgot-password · reset-password`. **Everything else requires a session**; `/api/admin/*` also requires the `admin`
role. With `APP_API_TOKEN` set, every route except health also requires the proxy's token.

**Pages.** `src/proxy.ts` (Next.js 16's renamed middleware) only redirects visitors *without any* session cookie to
`/login?next=…`; the `(app)` layout then asks FastAPI (`/api/auth/me`, forwarding just the session cookie and the
service token, uncached) and redirects expired sessions. `next` is restricted to same-site paths (no `//`, `\`,
absolute URLs, API or auth pages). On any `401` from the API, or when another tab switched accounts, the client
cancels in-flight requests (uploads and answer streams included) and reloads into the sign-in page, so no data from
the previous user survives in memory.

## Tech stack

| Layer | Choices |
|---|---|
| Frontend | Next.js 16 (App Router, Turbopack, route-handler proxy), React 19, TypeScript, Tailwind CSS 4, react-markdown + KaTeX, lucide icons, sonner |
| Backend | Python 3.12, FastAPI, Pydantic v2 / pydantic-settings, SQLAlchemy 2, Alembic, Uvicorn; pwdlib (Argon2id), email-validator, smtplib |
| Data | PostgreSQL + **pgvector** (HNSW, cosine), full-text `tsvector` + GIN with BM25 scoring; SQLite fallback (numpy + in-process BM25) |
| Parsing | pypdf, python-pptx, python-docx, Markdown/TXT with encoding detection |
| AI | Anthropic Python SDK (Claude: streaming, structured outputs, refusal fallbacks), OpenAI SDK (any compatible endpoint), fastembed (BAAI/bge-small-en-v1.5, ONNX) |
| Quality | pytest (158 tests on SQLite **and** pgvector, 93% coverage), Vitest + Testing Library (49), Playwright E2E with a real SMTP server and mobile checks, retrieval benchmark, Ruff, ESLint, `tsc` |
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
- **Authorisation where the data is.** Ownership is enforced in one module of ownership-scoped queries
  (`services/access.py`) that every route and the streaming/background code paths use — not by hiding buttons and
  not by relying on unguessable UUIDs. A 30-endpoint cross-user test asserts `404` everywhere and that nothing changed.
- **Revocable, server-side sessions instead of JWTs.** Sign-out, password resets and disabling an account take
  effect on the next request; the database never holds a usable token.
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
│   │   ├── api/routes/        # auth, admin, courses, demo, documents (+chunks, re-index), chat (+SSE, search), quizzes, flashcards, health
│   │   ├── api/deps.py        # CurrentUser / AdminUser, CSRF dependency, ownership-checked lookups
│   │   ├── core/              # settings (+ production guard), security (cookies, CSRF, client IP), errors, logging
│   │   ├── db/                # engine/session, cross-dialect types (EmbeddingVector, UTCDateTime)
│   │   ├── models/ · schemas/ # SQLAlchemy models (incl. users, auth_sessions…) · Pydantic request/response models
│   │   ├── cli.py             # create admins, roles, enable/disable, assign legacy courses, cleanup
│   │   ├── services/
│   │   │   ├── auth.py        # Argon2id, sessions, password policy, reset tokens, cleanup
│   │   │   ├── access.py      # ownership-scoped queries used by every route
│   │   │   ├── mailer.py · rate_limit.py   # SMTP / outbox / memory mailers · DB-backed rate limits
│   │   │   ├── parsing.py     # PDF / PPTX / DOCX / MD / TXT → location-tagged sections (+ limits)
│   │   │   ├── chunking.py    # structure-aware splitter with overlap
│   │   │   ├── embeddings.py  # fastembed · OpenAI · hashing providers + signatures
│   │   │   ├── ingestion.py   # background pipeline + status state machine
│   │   │   ├── retrieval.py   # pgvector + BM25-on-FTS / numpy + BM25, RRF, index-version check
│   │   │   ├── chat.py        # RAG orchestration, citation validation, sessions
│   │   │   ├── quizzes.py · flashcards.py · srs.py
│   │   │   └── llm/           # prompts, Claude / OpenAI-compatible / offline backends
│   │   └── main.py            # app factory (lifespan, CORS, service token, security + no-store headers, routers)
│   ├── alembic/               # migrations (pgvector, HNSW + GIN indexes, embedding signatures, accounts + ownership)
│   ├── scripts/               # dev_db · seed_demo · evaluate_retrieval · capture_screenshots · make_sample_data
│   └── tests/                 # 158 pytest tests (SQLite + PostgreSQL), incl. auth, isolation, CSRF, migrations
├── frontend/
│   ├── src/app/(auth)/        # /login · /register · /forgot-password · /reset-password
│   ├── src/app/(app)/         # signed-in pages: dashboard, /courses/[courseId]/{materials,ask,quiz,flashcards}, /admin
│   ├── src/app/api/[...path]/ # same-origin proxy (cookies, CSRF header, streaming, Set-Cookie passthrough)
│   ├── src/proxy.ts           # redirect hint for visitors without a session cookie (not an authorisation check)
│   ├── src/components/        # UI kit, auth forms, auth context + header, Markdown + citations, source cards…
│   └── src/lib/               # API client (CSRF, 401 handling), server-side session check, SSE parser, helpers (+ tests)
├── evaluation/                # labelled retrieval questions, results, write-up
├── sample_data/               # demo course: 6-page PDF lecture, 8-slide PPTX with notes, Markdown guide
├── docs/                      # VERIFICATION.md, screenshots
├── docker-compose.yml · .env.example · .github/workflows/ci.yml
```

## Quick start with Docker

Requirements: Docker with Compose v2.24+.

```bash
cp .env.example .env          # set APP_API_TOKEN (any long random value); optional: ANTHROPIC_API_KEY, SMTP_*, ...
docker compose up --build
docker compose exec backend python -m app.cli create-user --email you@example.com --admin   # optional admin
```

Open <http://localhost:3000>, **create an account**, then click **Demo course** to load and index the sample
materials. API docs are at <http://127.0.0.1:8000/docs> (the API is bound to loopback; the browser goes through the
frontend's proxy). The backend image bakes in the local embedding model and runs `alembic upgrade head` before
starting; Postgres data, uploads and the development mail outbox live in named volumes. Password-reset mail goes to
the outbox by default (`docker compose exec backend ls /app/data/outbox`); `docker compose --profile mail up` adds a
Mailpit inbox at <http://localhost:8025> (set `MAIL_BACKEND=smtp`, `SMTP_HOST=mailpit`, `SMTP_PORT=1025`,
`SMTP_STARTTLS=false`).

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
python -m app.cli create-user --email you@example.com --admin     # optional: an admin account
```

The first run downloads the ~65 MB embedding model (`BAAI/bge-small-en-v1.5`, ONNX) into `backend/data/models`.
In development, password-reset emails are written as `.eml` files to `backend/data/outbox/` (`MAIL_BACKEND=outbox`);
open the newest one to follow the link.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local               # BACKEND_URL=http://127.0.0.1:8000 (+ the same APP_API_TOKEN if set)
npm run dev                              # http://localhost:3000 → create an account → "Demo course"
```

`APP_PUBLIC_URL` on the backend must be the exact address you open in the browser (`http://localhost:3000`, not
`127.0.0.1:3000`): it is the trusted origin for every state-changing request.

## Configuration

All backend settings are environment variables (or `.env` / `backend/.env`); see [`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `production` refuses unsafe settings at startup (see [Accounts & security](#accounts--security)) |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/course_assistant` | SQLAlchemy URL (PostgreSQL + pgvector, or SQLite) |
| `AUTO_MIGRATE` | `true` | Run Alembic migrations on startup (`false` in the Docker image, which migrates explicitly) |
| `APP_PUBLIC_URL` | `http://localhost:3000` | The address users open: trusted CSRF origin and base of reset links (`https://` in production) |
| `APP_API_TOKEN` | — | Shared secret between the Next.js proxy and the API (required in production, ≥ 32 chars). All `/api` routes except health then require it. Same value for the frontend |
| `SESSION_COOKIE_NAME` / `CSRF_COOKIE_NAME` | `aica_session` / `aica_csrf` | Use `__Host-…` names behind HTTPS; the frontend needs the same names |
| `SESSION_COOKIE_SECURE` / `SESSION_COOKIE_SAMESITE` | `false` / `lax` | `true` behind HTTPS (enforced in production); `strict` is possible |
| `SESSION_TTL_SECONDS` / `SESSION_REMEMBER_TTL_SECONDS` / `SESSION_IDLE_TIMEOUT_SECONDS` | `43200` / `2592000` / `604800` | 12 h, 30 days with *Remember me*, 7 days idle |
| `REGISTRATION_ENABLED` | `true` | `false` closes sign-up (admins create accounts with the CLI) |
| `PASSWORD_MIN_LENGTH` / `PASSWORD_MAX_LENGTH` / `PASSWORD_RESET_TTL_SECONDS` | `15` / `128` / `1800` | Password policy · reset-link lifetime |
| `MAIL_BACKEND` | `outbox` | `smtp` (production) · `outbox` (`.eml` files in `MAIL_OUTBOX_DIR`, dev only) · `disabled` (reset answers `503`) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` | — / `587` / — / — / — | Required for `MAIL_BACKEND=smtp` (host and from) |
| `SMTP_STARTTLS` / `SMTP_SSL` | `true` / `false` | STARTTLS (587) or implicit TLS (465) |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_*` | `true` / see `.env.example` | `<requests>/<seconds>` per IP and per account for sign-in, sign-up and resets |
| `CSRF_TRUSTED_ORIGINS` | — | Extra origins allowed to send state-changing requests |
| `TRUSTED_PROXY_IPS` | `127.0.0.1,::1` | Peers (IPs/CIDRs) whose `X-Forwarded-For` is believed; requests with `APP_API_TOKEN` always are |
| `CORS_ORIGINS` | — | Only for browser apps on *other* origins calling the API directly (exact origins, credentials) |
| `MAX_UPLOAD_MB` / `MAX_PAGES` / `MAX_DOCUMENT_CHARS` / `MAX_UNZIPPED_MB` | `25` / `500` / `2000000` / `200` | Upload and parsing limits |
| `UPLOAD_DIR` / `DEMO_DIR` | `backend/data/uploads` / `sample_data` | Original files / demo-course materials |
| `LLM_PROVIDER` | `auto` | `auto` · `anthropic` · `openai` · `offline` (`auto`: Anthropic → OpenAI-compatible → offline, based on which keys exist) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / `claude-opus-5-5` | Claude |
| `ANTHROPIC_EFFORT` / `ANTHROPIC_FALLBACKS` | `medium` / `true` | Effort level (blank for models without it) / server-side refusal fallback |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | — | Any OpenAI-compatible endpoint (e.g. DeepSeek `https://api.deepseek.com/v1` + `deepseek-chat`, Ollama `http://localhost:11434/v1`) |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `fastembed` / `BAAI/bge-small-en-v1.5` / `384` | For Chinese/multilingual notes: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` / `RETRIEVAL_TOP_K` | `1000` / `150` / `6` | Chunking and retrieval |
| `BACKEND_URL` *(frontend)* | `http://127.0.0.1:8000` | Where the Next.js proxy forwards `/api` (runtime) |
| `APP_API_TOKEN` · `SESSION_COOKIE_NAME` · `CSRF_COOKIE_NAME` *(frontend)* | — · `aica_session` · `aica_csrf` | Same values as the backend (runtime, server-side only — nothing is `NEXT_PUBLIC_*`) |
| `TRUSTED_PROXY_COUNT` *(frontend)* | `0` | Reverse proxies in front of Next.js that append to `X-Forwarded-For` (`1` behind nginx/Caddy) |

## Database & migrations

| Table | Purpose |
|---|---|
| `users` | Normalised email (unique), Argon2id hash, display name, `role` (`user`/`admin`), `is_active`, last sign-in |
| `auth_sessions` | SHA-256 of the session token (unique), remember flag, `expires_at`, `last_seen_at` (idle timeout), `revoked_at` |
| `password_reset_tokens` | SHA-256 of the reset token (unique), `expires_at`, `used_at` |
| `rate_limit_counters` | Hashed `scope:identifier:window` keys with counts and expiry |
| `courses` | Course metadata and `owner_id` (everything below inherits access through it) |
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

### Upgrading a database that predates accounts (migration `0003`)

Migration `0003` adds the account tables and `courses.owner_id`. Existing courses are **kept, owned by nobody and
visible to nobody** — they are never given to whoever signs up first. `owner_id` stays nullable only for those
legacy rows; new rows must have an owner (an ORM check everywhere, plus a `NOT VALID` `CHECK` constraint on
PostgreSQL that guards new and updated rows without rejecting the old ones).

```bash
pg_dump -Fc -f before-accounts.dump postgresql://postgres:postgres@localhost:5432/course_assistant   # 1. back up (+ UPLOAD_DIR)
cd backend && alembic upgrade head                                                  # 2. migrate (or just start the API)
python -m app.cli create-user --email you@example.com --admin                       # 3. an account to own them
python -m app.cli list-orphan-courses                                               # 4. see what's unassigned
python -m app.cli assign-course --course-id <id> --email you@example.com            #    one by one, or
python -m app.cli assign-orphans --email you@example.com --yes                      #    all to one account
python -m app.cli validate-ownership                                                # 5. fully enforce (PostgreSQL)
```

Rollback: `alembic downgrade 0002` removes the account tables and `owner_id` but keeps every course and its content
(ownership is lost); restoring the dump returns to the exact earlier state. Destructive migration tests run only on
throw-away databases (`tests/test_migrations.py` creates and drops its own PostgreSQL database).

### Housekeeping

`python -m app.cli cleanup` deletes expired or revoked sessions and used/expired reset tokens older than 7 days, and
expired rate-limit windows. It is safe to run any time — e.g. hourly from cron
(`0 * * * * cd /app && python -m app.cli cleanup`), a systemd timer, Windows Task Scheduler or
`docker compose exec backend python -m app.cli cleanup`.

## API

Interactive docs: `/docs` on the backend. All 44 operations live under `/api`. Everything except health and the
anonymous auth endpoints needs a session cookie, and only ever returns the caller's own data (`404` otherwise).

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status, DB dialect, active LLM / embedding providers and signature *(public)* |
| GET | `/auth/csrf` | CSRF token for `X-CSRF-Token` (sets the pre-login double-submit cookie) *(public)* |
| POST | `/auth/register` · `/auth/login` | `{email, password, password_confirm, display_name?}` · `{email, password, remember_me}` → `{user, csrf_token}` + session cookie *(public)* |
| POST | `/auth/logout` | Revoke this session and clear the cookies *(public)* |
| GET | `/auth/me` | The signed-in user |
| POST | `/auth/forgot-password` · `/auth/reset-password` | Email a reset link (`202`, same answer for any address) · `{token, password, password_confirm}` *(public)* |
| GET · PATCH | `/admin/users` · `/admin/users/{id}` | List accounts · `{is_active}` (admin only) |
| GET · POST | `/courses` | Your courses (with dashboard stats) · create (you become the owner) |
| GET · PATCH · DELETE | `/courses/{id}` | Read · update · delete (cascades) |
| POST | `/demo` | Create (or return) *your* demo course from `sample_data/` |
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

From the command line, behave like the browser: keep cookies, send the page's `Origin` and the CSRF token on
every state-changing request (through the frontend proxy, which adds the service token):

```bash
APP=http://localhost:3000; JAR=cookies.txt
CSRF=$(curl -s -c $JAR $APP/api/auth/csrf | python -c "import sys, json; print(json.load(sys.stdin)['csrf_token'])")
CSRF=$(curl -s -b $JAR -c $JAR -H "Origin: $APP" -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your long passphrase", "remember_me": false}' \
  $APP/api/auth/login | python -c "import sys, json; print(json.load(sys.stdin)['csrf_token'])")   # new session → new token
curl -b $JAR $APP/api/courses
```

```bash
curl -b $JAR -H "Origin: $APP" -H "X-CSRF-Token: $CSRF" -F "files=@sample_data/Lecture03_Gradient_Descent.pdf" $APP/api/courses/$COURSE/documents
```

```bash
curl -N -b $JAR -H "Origin: $APP" -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/json" -d '{"question": "How should I choose a learning rate?"}' $APP/api/courses/$COURSE/chat/stream
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
status: `401 authentication_required / session_expired / invalid_credentials / service_token_invalid`,
`403 csrf_failed / origin_required / origin_not_allowed / forbidden / account_disabled`, `404`,
`409 email_taken / duplicate_document / no_materials / index_outdated`, `413`, `415`, `422 validation_error`
(`details` lists `{field, message}`; submitted values are never echoed), `429 rate_limited` (+ `Retry-After`),
`502 llm_*`, `503 password_reset_unavailable`.

## Testing

```bash
cd backend
ruff check . && ruff format --check .
pytest                                    # SQLite, hashing embeddings, offline generator, memory mailer — no network
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/course_assistant_test pytest   # same tests on pgvector
pytest --cov=app                          # coverage (93% combined in CI)
python scripts/evaluate_retrieval.py --min-hybrid-recall5 0.9   # retrieval benchmark (see evaluation/)
```

The 158 backend tests sign in through the real API (no mocked auth, no bypass switch) and cover, among others:
registration and validation, email normalisation and the unique constraint under concurrent sign-ups, Argon2id
hashes, uniform login failures, remember-me, idle/absolute expiry, forged/revoked cookies and replay after sign-out,
sessions surviving an API restart; password reset (uniform answers, expiry, reuse, concurrent use of one token,
revocation of all sessions, real SMTP delivery to a local server, no secrets in logs); **two-user isolation across 30
endpoints** (incl. SSE, files, nested ids and owner injection); admin role checks, disabled accounts, per-user demo
courses and legacy courses; CSRF/origin attacks, rate limits, trusted `X-Forwarded-For`, CORS and `no-store`; and
migrations with pre-existing data, rollback and re-upgrade on SQLite **and** on a throw-away PostgreSQL database.

```bash
cd frontend
npm ci && npx next typegen && npm run lint && npm run typecheck && npm test && npm run build
```

The 49 frontend tests include the proxy (cookie allowlist both ways, one `Set-Cookie` per cookie with `Domain`
stripped, `no-store`, client address), the API client (CSRF token, retry on a stale token, 401 handling, cancelling
requests on sign-out), the open-redirect guard and the sign-in/sign-up forms.

End-to-end, with the stack running and the backend sending mail to `127.0.0.1:2525` (`MAIL_BACKEND=smtp`,
`SMTP_HOST=127.0.0.1`, `SMTP_PORT=2525`, `SMTP_STARTTLS=false`, `APP_PUBLIC_URL` = the web address):

```bash
pip install playwright httpx aiosmtpd
python backend/scripts/capture_screenshots.py --web http://localhost:3000
```

It drives your installed Edge/Chrome through sign-up → refresh → demo course → upload → retrieval → streaming chat →
passage viewer → original PDF → quiz → flashcards → mobile layout (signed in and out) → sign-out → cookie replay →
protected redirect → sign-in back to the requested page → forgot password → the emailed link → reset → old password
refused, and refreshes `docs/screenshots/`.

CI runs both backend suites with a combined coverage gate (≥ 85%), the retrieval benchmark gate, frontend
lint/typecheck/tests/build, and builds both Docker images. What was and wasn't verified is recorded in
[`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## Deployment

- **Database:** managed PostgreSQL with pgvector — Neon, Supabase, AWS RDS / Aurora, Azure Flexible Server, Cloud SQL.
- **Backend:** the `backend/Dockerfile` image on Render, Fly.io, Railway, Cloud Run, ECS or a VM. Set
  `APP_ENV=production`, `DATABASE_URL`, `APP_PUBLIC_URL=https://…`, `APP_API_TOKEN`, `SESSION_COOKIE_SECURE=true`
  (with `__Host-` cookie names), `MAIL_BACKEND=smtp` + `SMTP_*`, and provider keys — from the platform's secret
  manager, never the repository. The app refuses to start if any of the security-relevant ones are unsafe. Mount
  persistent storage for `UPLOAD_DIR` (or add object storage). Keep it on a private network — only the frontend needs
  to reach it. One worker per instance while ingestion runs in-process. Schedule `python -m app.cli cleanup`.
- **Frontend:** the `frontend/Dockerfile` standalone image with `BACKEND_URL`, the same `APP_API_TOKEN` and cookie
  names as runtime environment variables — no rebuild needed to point at another backend.
- **HTTPS:** terminate TLS in front of the frontend (Caddy, nginx, a load balancer). If that proxy appends
  `X-Forwarded-For`, set `TRUSTED_PROXY_COUNT=1` on the frontend so rate limits see real client addresses.
- **Admins:** `python -m app.cli create-user --email … --admin` once; there is no default admin account.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `403 origin_not_allowed` / `origin_required` on every action | `APP_PUBLIC_URL` must be exactly the address in the browser bar (scheme, host and port; `localhost` ≠ `127.0.0.1`). Add others to `CSRF_TRUSTED_ORIGINS`. Scripts must send `Origin` |
| `403 csrf_failed` | Fetch a token from `GET /api/auth/csrf` (or use the one returned by login) and send it as `X-CSRF-Token`; the web app retries this automatically once |
| Signed in, but immediately back on the sign-in page | The session cookie isn't stored: with `SESSION_COOKIE_SECURE=true` (or `__Host-` names) the site must be served over HTTPS; cookie names must match between frontend and backend |
| "The study service is unavailable" | The frontend can't reach `BACKEND_URL`, or `APP_API_TOKEN` differs between frontend and backend (`401 service_token_invalid`) |
| Startup fails with "Unsafe production configuration" | `APP_ENV=production` with an `http://` URL, insecure cookies, a short/missing `APP_API_TOKEN` or the outbox mailer — fix the listed items |
| No reset email arrives | `MAIL_BACKEND=outbox` writes files to `MAIL_OUTBOX_DIR` instead of sending; with `smtp`, check the API log for "Could not deliver" (the link itself is never logged) |
| `429 rate_limited` while testing | Wait for `Retry-After` (counters expire with their window) or raise the `RATE_LIMIT_*` values in development |
| Old courses disappeared after upgrading | They're intact but have no owner yet: `python -m app.cli list-orphan-courses`, then `assign-course` |

## Known limitations

- **Accounts are deliberately minimal:** no email verification (a sign-up proves nothing about the address, and the
  sign-up form necessarily reveals whether an email is registered — mitigated by rate limits), no MFA/passkeys, no
  OAuth/SSO, no self-service email or password change while signed in (use the reset flow), no account deletion.
- **Rate limits are per process-shared fixed windows** (bursts of up to 2× at a window boundary). Per-address limits
  depend on the proxy chain being configured (`TRUSTED_PROXY_COUNT` / `TRUSTED_PROXY_IPS`); when Next.js is exposed
  directly, a client can choose its own `X-Forwarded-For`, so only the per-account limits are robust there.
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

- Email verification, MFA/passkeys, OAuth sign-in; shared class spaces with roles per course
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
- Added **multi-user accounts with per-user data isolation**: Argon2id passwords, revocable server-side sessions in
  HttpOnly cookies (only token hashes stored), session-bound CSRF tokens with strict Origin checks, database-backed
  rate limiting, and an email password-reset flow with single-use, race-safe tokens; ownership enforced in every
  query and verified by a 30-endpoint cross-user test; a zero-data-loss migration isolates pre-existing courses.
- Shipped with **158 backend tests on SQLite and PostgreSQL (93% coverage)**, 49 frontend tests, a Playwright
  end-to-end suite (sign-up to password reset via a real SMTP server, mobile layout checks), a same-origin Next.js API
  proxy, Docker Compose, Alembic migrations and GitHub Actions CI with coverage and retrieval-quality gates.

<details>
<summary>中文版（简历要点）</summary>

**AI Course Assistant（AI 课程助手）** — 全栈检索增强（RAG）学习助手 · Python、FastAPI、PostgreSQL/pgvector、Next.js、TypeScript、Docker

- 独立实现全栈 RAG 学习应用：将课件 PDF、PPT 与笔记转化为**精确到页码/幻灯片引用**的 SSE 流式问答、可自动判分的测验，以及基于 SM-2 间隔重复的闪卡复习。
- 设计**混合检索**：pgvector HNSW 语义检索 + 基于 PostgreSQL GIN 全文索引计算的 BM25，经 RRF 融合；在 33 题人工标注评测集上混合检索 **Recall@5 达 1.00、MRR 0.92**，优于纯向量检索（MRR 0.83），5/5 个超纲问题被识别、零误报；消融实验发现并修复了缺少 IDF 的排序缺陷（关键词 Recall@1 0.64 → 0.86）。
- 保证回答可核查、可控：服务端引用校验与来源快照、原文段落查看、提示注入防护、低置信度拒答，以及防止混用不同向量空间的 embedding 版本管理。
- 以任务级接口抽象 LLM 提供方（Anthropic SDK 结构化输出调用 Claude、任意 OpenAI 兼容接口、确定性离线模式），对生成内容进行校验与修复。
- 实现**多用户账号与数据隔离**：Argon2id 密码哈希、可撤销的服务端会话（HttpOnly Cookie，数据库只存令牌摘要）、与会话绑定的 CSRF 令牌和严格 Origin 校验、基于数据库的限流，以及一次性、并发安全令牌的邮件找回密码；所有查询按所有者授权并由覆盖 30 个接口的跨用户测试验证；迁移零数据丢失并隔离历史课程。
- 工程化交付：**158 个后端测试同时在 SQLite 与 PostgreSQL 上运行（覆盖率 93%）**、49 个前端测试、Playwright 端到端测试（从注册到经真实 SMTP 服务器重置密码，含移动端检查）、Next.js 同源代理、Docker Compose、Alembic 迁移，以及带覆盖率与检索质量门槛的 GitHub Actions CI。

</details>

## License

[MIT](LICENSE)
