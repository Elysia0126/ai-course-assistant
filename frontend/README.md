# AI Course Assistant — Frontend

Next.js 16 (App Router) + TypeScript + Tailwind CSS v4 client for the FastAPI backend.
See the [project README](../README.md) for the full setup, architecture, security model and API docs.

```bash
npm install
cp .env.example .env.local   # BACKEND_URL=http://127.0.0.1:8000 (+ APP_API_TOKEN if the backend sets one)
npm run dev                  # http://localhost:3000 → create an account
```

| Script              | What it does                         |
| ------------------- | ------------------------------------ |
| `npm run dev`       | Dev server with Turbopack            |
| `npm run build`     | Production build (`output: standalone`) |
| `npm run lint`      | ESLint (flat config, `eslint-config-next`) |
| `npm run typecheck` | `tsc --noEmit` (run `npx next typegen` first on a fresh checkout) |
| `npm test`          | Vitest unit/component tests (jsdom; the proxy and API client run in node) |

```
src/
├── proxy.ts                   # redirect hint: no session cookie → /login?next=… (never an authorisation check)
├── app/
│   ├── (auth)/                # /login · /register · /forgot-password · /reset-password (no-referrer)
│   ├── (app)/                 # signed-in pages; layout.tsx asks FastAPI /api/auth/me on the server
│   │   ├── page.tsx           # course dashboard
│   │   ├── courses/[courseId]/ # layout (tabs) + materials · ask · quiz · flashcards
│   │   └── admin/             # account list, enable/disable (admins only)
│   └── api/[...path]/         # same-origin proxy to FastAPI (streams uploads + SSE, auth cookies both ways, service token)
├── components/                # UI primitives, auth forms + context, header, markdown + citation chips, source cards…
└── lib/                       # API client (CSRF, 401 handling), server-only session check, SSE parser, helpers
```

## How authentication works here

- **Runtime configuration only** (`BACKEND_URL`, `APP_API_TOKEN`, `SESSION_COOKIE_NAME`, `CSRF_COOKIE_NAME`,
  `TRUSTED_PROXY_COUNT`), read on the server. Nothing is `NEXT_PUBLIC_*`, so no secret reaches the browser bundle,
  and the browser always calls the same-origin `/api` (there is no direct-to-backend mode).
- **The proxy** forwards only the session and CSRF cookies, the `X-CSRF-Token`, `Origin` and `Referer` headers, and
  the client address; it adds the service token; it returns each backend `Set-Cookie` as its own header without a
  `Domain`; it marks responses `private, no-store`; request and response bodies stay streamed.
- **Server-side session check:** the `(app)` layout calls `getSession()` (`src/lib/server-auth.ts`, `server-only`,
  uncached, deduplicated per render with `React.cache`), which forwards just the session cookie and the service
  token to `/api/auth/me`. Anonymous or expired → redirect to `/login?next=…`; API unreachable → an error page, not a
  login loop. `safeNextPath()` only allows same-site paths.
- **Client:** `src/lib/api.ts` keeps the CSRF token in memory (from `/api/auth/csrf` or the login response), sends it on
  every state-changing request (fetch, XHR uploads, the SSE `POST`) and retries once if it went stale. A `401` with
  `authentication_required`/`session_expired` cancels every in-flight request and reloads into `/login`; sign-out and
  account switches (detected when a tab becomes visible) do the same, so nothing of the previous user stays in memory.
