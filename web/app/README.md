# TradingAgents web app

Next.js (App Router) frontend for the TradingAgents Indian-equity research engine — search a ticker, watch a run progress, read the verdict and the full evidence behind it.

## Environment

Copy `.env.local.example` to `.env.local`. Both variables are needed, and they are deliberately duplicated: server-side fetches (RSC) run in Node and read `API_BASE_URL`, while browser fetches read `NEXT_PUBLIC_API_BASE_URL`, which Next.js inlines into the client bundle **at build time**.

| Variable | Used by | Default if unset |
| --- | --- | --- |
| `API_BASE_URL` | Server Components, server-side fetches | `http://127.0.0.1:8000` |
| `NEXT_PUBLIC_API_BASE_URL` | Browser fetches (polling, form submits) | `http://127.0.0.1:8000` |

**Deployment risk:** because `NEXT_PUBLIC_API_BASE_URL` is baked in at build time, a production build made without it falls back to `http://127.0.0.1:8000` — which points every visitor's browser at *their own machine*, not your server. Set it in the build environment, not just at runtime, and rebuild after changing it.

## Backend

Nothing works without the FastAPI backend, which is **two processes** (see the repo root `DEV_HANDOFF.md`):

```bash
python -m uvicorn api.main:app --reload   # the API
python -m api.worker                      # executes queued analyses
```

Without the worker, submitted runs sit at `queued` forever. That is expected, not a bug.

## Commands

```bash
npm run dev        # dev server on http://localhost:3000
npm run build      # production build
npm test           # unit + component tests (Vitest)
npm run test:e2e   # end-to-end tests (Playwright)
npm run lint       # ESLint
```

`npm run test:e2e` starts its own mock API on port 8010 and a dev server on port 3100, so the E2E suite never needs the real backend and never spends LLM money. Unit tests stub `fetch` and need nothing running.

`npm run generate:api-types` regenerates `src/lib/api-client/types.gen.ts` from `api/openapi.json`; that file is generated, don't hand-edit it. The hand-written wrapper in `src/lib/api-client/client.ts` is where API behaviour the spec doesn't capture (200-vs-202 on `POST /analyze`, 429 bodies) is encoded.
