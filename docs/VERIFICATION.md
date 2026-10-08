# Verification record

What was actually executed, where, and what was only configured. Last updated 2026-10-07 (accounts & login).

Local machine: Windows 11, Python 3.12.15, Node.js 24.21, Next.js 16.3.8, PostgreSQL 16.2 + pgvector 0.6.2
(embedded via `pgserver`), local embeddings `BAAI/bge-small-en-v1.5` (fastembed/ONNX), Microsoft Edge (Playwright).
Remote: GitHub Actions `ubuntu-latest` with the `pgvector/pgvector:pg17` service container.

## Automated checks

| Check | Where | Result |
|---|---|---|
| Backend tests on SQLite (hash embeddings, offline generator, in-memory mailer) | local + CI | **157 passed**, 1 skipped (the PostgreSQL-only migration test) |
| Same suite on PostgreSQL + pgvector (HNSW, BM25 over `tsvector`/GIN, JSONB, `NOT VALID` check) | local (PG 16) + CI (PG 17) | **158 passed** |
| Combined statement coverage (SQLite + PostgreSQL runs) | local + CI (gate ≥ 85%) | **93.4%** |
| Ruff lint + format | local + CI | clean |
| Frontend `npm ci`, `next typegen`, ESLint, `tsc --noEmit`, Vitest (**49 tests**), production build | local + CI | passed |
| Retrieval evaluation gate (hybrid Recall@5 ≥ 0.9), now run through the authenticated API | local + CI | Recall@5 = 1.00 (hash embeddings) |
| Docker images (`docker compose build`) | CI | both built |

CI run [37720305083](https://github.com/Elysia0126/ai-course-assistant/actions/runs/37720305083) (commit `bbe7a31`)
reproduced every number above: 157 + 1 skipped on SQLite, 158 on PostgreSQL 17, 93.43% combined coverage, 49
frontend tests, the retrieval gate and both image builds.
| Alembic upgrade → downgrade → upgrade with **pre-existing data** (courses, documents, chunks, chats) | local SQLite + a throw-away PostgreSQL database | data kept, owners `NULL`, PG indexes intact, `NOT VALID` check rejects new ownerless rows |

What the account tests cover: registration (validation, normalised unique email, concurrent duplicates, Argon2id,
no secrets in responses), sign-in (uniform failures, remember-me lifetimes, session rotation, planted cookies),
sessions (idle and absolute expiry, forged/revoked cookies, replay after sign-out, disabled accounts, survival
across an API restart), password reset (uniform answers, mail content, expiry, reuse, superseded tokens, four
concurrent submissions of one token → exactly one success, revocation of every session, delivery to a real local
SMTP server, no passwords/tokens in logs), **two-user isolation over 30 endpoints** (including SSE, original files,
chunk detail, attempts, reviews and resets; nested `document_ids` / `session_id` / question ids; owner injection),
admin role checks and guards, per-user demo courses, legacy ownerless courses and the CLI, CSRF/Origin attacks
(missing, foreign, wrong scheme/port, `null`, foreign token, stale token, login CSRF), rate limits with
`Retry-After`, trusted vs. spoofed `X-Forwarded-For`, CORS with credentials, `no-store` caching, and every
production-configuration refusal.

## Real upgrade of an existing database

The local development database still held a course created before accounts existed. Starting the new API applied
migration `0003` to it; afterwards `python -m app.cli list-orphan-courses` listed that course (kept, owner `NULL`),
`list-users` was empty, `validate-ownership` refused (exit 1) because an orphan remained, and no account could see
the course.

## End-to-end (real browser)

`backend/scripts/capture_screenshots.py` drives Microsoft Edge (Playwright) against the production build
(`next start`) → same-origin `/api` proxy (with `APP_API_TOKEN`) → FastAPI → PostgreSQL + pgvector, with the backend
sending mail over SMTP to an `aiosmtpd` server started by the script. Every step is an assertion:

1. `/` without a session redirects to `/login?next=%2F`.
2. Sign-up (fresh address, random password) lands on the dashboard; the session cookie is `HttpOnly`, `SameSite=Lax`
   and invisible to `document.cookie`; a reload keeps the session.
3. Demo course (created for this user only), **upload through the UI**, materials, retrieval inspector.
4. The original PDF is served through the proxy with `private, no-store`; a browser context without a session gets 401.
5. Streaming chat with cited sources and the passage viewer; quiz generation and grading; flashcard study.
6. Mobile (390 × 844): no horizontal overflow on signed-in pages and on `/login`, `/register`, `/forgot-password`;
   no clipped source cards.
7. Sign-out → `/login?reason=signed-out`, cookie gone; **replaying the old session cookie in a new context → 401**;
   opening a course page redirects to `/login?next=…`.
8. Signing in again (with *Remember me*, cookie lifetime > 29 days) returns to the requested page.
9. Forgot password → the email arrives **over SMTP** → the link opens `/reset-password`, the token disappears from
   the address bar, `<meta name="referrer" content="no-referrer">` is present → new password set →
   `/login?reason=reset` → the old password is refused, the new one works.
10. A non-admin opening `/admin` sees "Administrators only".

The screenshots in [`docs/screenshots/`](screenshots) are produced by this run.

Additional live checks against the same running stack (scripted with httpx and with `curl.exe`, 13/13 + 7/7 passed):
anonymous CSRF cookie attributes through the proxy; cross-origin write → 403 (proxy); write without `Origin` →
403 `origin_required` (FastAPI); wrong CSRF token → 403; calling FastAPI directly without the service token → 401
while `/api/health` stays public; sign-up returns **two separate `Set-Cookie` headers** through the proxy; private
responses carry `no-store`; SSE through the proxy delivered **101 separate `token` events**; ten wrong passwords
then **429 with `Retry-After`** (even for the right password); sign-out → 204 with both cookies cleared and the old
cookie rejected; the README's curl sequence (cookie jar + `Origin` + `X-CSRF-Token`, multipart upload) works.

## Bugs found by verification (and fixed)

| Found by | Problem | Fix |
|---|---|---|
| PostgreSQL test run | `Set-Cookie` `Expires` failed: psycopg returns timestamps in the connection's time zone, Starlette requires UTC | `UTCDateTime` now always returns UTC; cookies convert defensively |
| Auth tests | `Max-Age` was one second short of the session lifetime (truncation) | Rounded, so cookie lifetime equals the database expiry |
| E2E screenshots | Edge drew its own password-reveal button next to ours | Hide `::-ms-reveal` |
| First live start | `CORS_ORIGINS=http://localhost:3000` (as in `.env.example`) crashed startup — pydantic-settings JSON-decodes list fields | `NoDecode` + comma parser, regression test |
| Retrieval evaluation | PostgreSQL keyword ranking used `ts_rank_cd` (no IDF): keyword Recall@1 0.64 vs 0.82 for BM25 on SQLite | BM25 computed from the GIN-indexed `tsvector` → 0.86 |
| E2E screenshots | Offline generator produced questions from "Speaker notes:" and "Lecture 3:" labels; pronoun-led sentences as answers | Structural-label and pronoun filters, tests |
| E2E mobile check | Grid columns grew to their content's min-width → 78–299 px horizontal overflow; source cards clipped | `minmax(0,1fr)` columns, clipping assertion in E2E |
| Restart after a killed session | Embedded Postgres crash recovery outlasted `pg_ctl`'s 10 s timeout | `dev_db.py` waits and re-attaches |

## Not verified

- **Running containers.** Images build in CI, but `docker compose up` (container start-up, health checks, the fixed
  frontend address used for `TRUSTED_PROXY_IPS`, volumes, the optional Mailpit profile) has not been run — there is
  no Docker engine on the development machine.
- **Real email delivery.** Mail was delivered over SMTP to a local test server (`aiosmtpd`), without TLS. No message
  was sent through a real provider, so STARTTLS/implicit TLS, authentication and deliverability (SPF/DKIM) are
  unverified.
- **Production HTTPS.** `Secure` / `__Host-` cookies and the `APP_ENV=production` guard are covered by unit tests;
  no HTTPS deployment behind a real reverse proxy (and `TRUSTED_PROXY_COUNT=1`) was run.
- **Real LLM calls.** No Anthropic or OpenAI-compatible API key was available. The adapters are tested against fake
  SDK clients; all runs above used the offline generator. Answer quality with a real model is unmeasured.
- **Scale.** Small corpora and a handful of users; no load tests (sessions and rate-limit counters are single-row
  lookups/upserts, but that hasn't been benchmarked).
- **Other browsers / macOS / Linux desktop.** E2E ran on Edge (Chromium) on Windows only.
