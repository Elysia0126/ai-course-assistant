# AI Course Assistant — Frontend

Next.js 16 (App Router) + TypeScript + Tailwind CSS v4 client for the FastAPI backend.
See the [project README](../README.md) for the full setup, architecture and API docs.

```bash
npm install
cp .env.example .env.local   # BACKEND_URL=http://127.0.0.1:8000 (read by the /api proxy at runtime)
npm run dev                  # http://localhost:3000
```

| Script              | What it does                         |
| ------------------- | ------------------------------------ |
| `npm run dev`       | Dev server with Turbopack            |
| `npm run build`     | Production build (`output: standalone`) |
| `npm run lint`      | ESLint (flat config, `eslint-config-next`) |
| `npm run typecheck` | `tsc --noEmit`                       |
| `npm test`          | Vitest unit/component tests (jsdom)  |

```
src/
├── app/                       # routes
│   ├── page.tsx               # course dashboard
│   ├── api/[...path]/         # same-origin proxy to FastAPI (streams uploads + SSE, CSRF check, service token)
│   └── courses/[courseId]/    # layout (tabs) + materials · ask · quiz · flashcards
├── components/                # UI primitives, markdown + citation chips, source cards…
└── lib/                       # typed API client, SSE parser, citation + SM-2 helpers
```
