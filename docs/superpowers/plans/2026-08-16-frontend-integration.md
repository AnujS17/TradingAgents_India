# Frontend + Backend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working Next.js frontend in `web/app/` that wires real screens (search, in-progress, results, history) to the existing FastAPI backend, matching the API's documented and undocumented behavior exactly.

**Architecture:** Next.js 15 App Router, TypeScript. Server Components do the initial data fetch per route (RSC `await fetch()`); a single Client Component (`RunView`) takes over polling via TanStack Query only while a run is `queued`/`running`. A hand-written `client.ts` wraps a generated OpenAPI type file and encodes the API's real branching behavior (200 vs 202, 429 body shape) that the spec alone doesn't fully capture. E2E tests run against a small hand-rolled mock HTTP server (not the live Python backend), so the suite is deterministic and free to run.

**Tech Stack:** Next.js 15 (App Router, TypeScript, Tailwind from `create-next-app` scaffolding only — no visual design work in this plan), `@tanstack/react-query` v5, `react-markdown` + `remark-gfm`, `openapi-typescript` (dev, codegen only), Vitest + Testing Library (unit/component tests), Playwright (E2E), `tsx` (dev, runs the E2E mock server).

**Spec:** `DEV_HANDOFF.md` (primary, written 2026-08-16) and `UI_HANDOFF.md` (deeper source for the API contract) at the repo root. `api/schemas.py`, `api/routers/runs.py`, and `api/ratelimit.py` were read directly to confirm behavior the OpenAPI spec understates.

## Global Constraints

- **Do not edit `tradingagents/`, `api/`, or `cli/`.** Another session owns the backend. (`DEV_HANDOFF.md`)
- **Never add `Co-Authored-By: Claude` or any AI attribution** to commits or PR bodies. (`DEV_HANDOFF.md`, standing repo rule)
- **Frame as research, not advice** — evidence (bull/bear cases, reports) is shown above the verdict, not a giant badge. (`UI_HANDOFF.md`)
- `POST /analyze` returns **200** for an existing run (free, instant) and **202** for a newly queued run (costs money) — the UI must branch on status code, not body shape. (`api/routers/runs.py`)
- **429** is real but absent from the OpenAPI spec. Body is `{"detail": "<message>"}` (render `detail` verbatim, it's pre-written UX copy) plus a `Retry-After` header in seconds. Three causes: kill switch, global daily cap (default 500/day), per-IP daily cap (default 10/day). **Cached GET reads are never blocked by 429** — the UI must say so, not show a dead end. (`api/ratelimit.py`, `api/settings.py`)
- **Never render a missing `price_target` / `entry_price` / `stop_loss` as `0`.** Render "Not set." A null level is a deliberate engine decision, not missing data. (`DEV_HANDOFF.md`)
- `verdict.rating` (5-tier: Buy/Overweight/Hold/Underweight/Sell) and `verdict.levels.action` (3-tier: Buy/Hold/Sell) are **independent fields** — never collapse into one badge. (`DEV_HANDOFF.md`)
- Tickers normalize **server-side**. Do not normalize client-side. (`api/schemas.py`)
- Reports total ~11,375 words across up to 10 fields (`sentiment` alone ~3,000 words). Must not dump into one unbroken scroll — use collapsible/tabbed sections. (`UI_HANDOFF.md`)
- `verdict_is_contested` (repeat runs of the same day's snapshot reaching different ratings) must be **surfaced, not hidden** behind whichever run is newest. (`DEV_HANDOFF.md`)
- The backend requires **two live processes** (`uvicorn api.main:app --reload` and `python -m api.worker`) for anything to execute; without the worker, runs sit at `queued` forever — expected, not a bug. This plan's automated tests never depend on either process being up (see Tasks 10–11); Task 12 is the only task that needs them.
- Do not call `force: true` repeatedly during manual verification — it costs real LLM money. Repeat the same ticker+date+profile without `force` instead (free, cached).
- No `package.json` exists anywhere in this repo yet — `web/app/` is a from-scratch scaffold.

---

## File Structure

```
web/
├── design/                                   # moved static comps (Task 1)
│   ├── DESIGN.md
│   ├── landing-fintech/index.html
│   ├── landing/index.html
│   └── research/index.html
└── app/                                       # new Next.js app (Task 2+)
    ├── package.json
    ├── next.config.ts
    ├── tsconfig.json
    ├── vitest.config.ts
    ├── playwright.config.ts
    ├── .env.local.example
    ├── src/
    │   ├── app/
    │   │   ├── layout.tsx                    # wraps children in <Providers>
    │   │   ├── providers.tsx                 # QueryClientProvider (Task 5)
    │   │   ├── page.tsx                       # home: search + recent runs (Task 7)
    │   │   ├── runs/[id]/page.tsx             # durable run link (Task 8)
    │   │   └── stock/[ticker]/[date]/page.tsx # canonical results page (Task 9)
    │   ├── components/
    │   │   ├── SearchForm.tsx                 # Task 7
    │   │   ├── RecentRuns.tsx                 # Task 7
    │   │   ├── RunStatusBanner.tsx            # Task 6
    │   │   ├── VerdictSummary.tsx             # Task 6
    │   │   ├── ReportsAccordion.tsx           # Task 6
    │   │   ├── RunHistoryPanel.tsx            # Task 6
    │   │   └── RunView.tsx                    # Task 6
    │   └── lib/
    │       ├── api-client/
    │       │   ├── types.gen.ts               # generated, do not hand-edit (Task 3)
    │       │   └── client.ts                  # hand-written wrapper (Task 3)
    │       ├── format.ts                      # Task 4
    │       └── poll.ts                        # Task 5
    ├── tests/
    │   ├── unit/
    │   │   ├── setup.ts
    │   │   ├── format.test.ts                 # Task 4
    │   │   ├── client.test.ts                 # Task 3
    │   │   ├── poll.test.ts                   # Task 5
    │   │   ├── components/
    │   │   │   ├── VerdictSummary.test.tsx     # Task 6
    │   │   │   └── RunHistoryPanel.test.tsx    # Task 6
    │   │   └── SearchForm.test.tsx             # Task 7
    │   └── e2e/
    │       ├── mock-server.ts                 # Task 10
    │       ├── fixtures/
    │       │   ├── completed.json             # Task 10 (copy of api/fixtures/sample_run.json)
    │       │   └── contested-history.json     # Task 10
    │       ├── search-to-result.spec.ts        # Task 11
    │       ├── failed-run.spec.ts              # Task 11
    │       ├── contested-history.spec.ts       # Task 11
    │       └── rate-limit.spec.ts              # Task 11
    └── public/
```

---

### Task 1: Move static comps into `web/design/`

**Files:**
- Move: `web/DESIGN.md` → `web/design/DESIGN.md`
- Move: `web/landing-fintech/` → `web/design/landing-fintech/`
- Move: `web/landing/` → `web/design/landing/`
- Move: `web/research/` → `web/design/research/`
- Modify: `DEV_HANDOFF.md`, `UI_HANDOFF.md` (path references, if any point at the old locations)

**Interfaces:** None — this task moves static files with no build step and no code dependencies.

- [ ] **Step 1: Create the target directory and move the files**

```bash
mkdir -p web/design
mv web/DESIGN.md web/design/DESIGN.md
mv web/landing-fintech web/design/landing-fintech
mv web/landing web/design/landing
mv web/research web/design/research
```

- [ ] **Step 2: Check the moved files for internal references to the old paths**

```bash
grep -rn "web/DESIGN\|web/landing\|web/research" web/design/ || echo "no internal path references found"
```

If any hits appear, they're almost certainly relative asset links inside the single-file HTML comps — open the matching file and fix the path relative to its new location under `web/design/`.

- [ ] **Step 3: Update path references in the handoff docs**

```bash
grep -n "web/DESIGN\.md\|web/landing-fintech\|web/research/index" DEV_HANDOFF.md UI_HANDOFF.md
```

For each hit in `DEV_HANDOFF.md`'s "What already exists" section, update `web/landing-fintech/index.html` → `web/design/landing-fintech/index.html`, `web/research/index.html` → `web/design/research/index.html`, and `web/DESIGN.md` → `web/design/DESIGN.md`.

- [ ] **Step 4: Verify nothing was left behind**

```bash
test ! -e web/DESIGN.md && test ! -d web/landing-fintech && test ! -d web/landing && test ! -d web/research && echo OK
test -f web/design/DESIGN.md && test -f web/design/research/index.html && test -f web/design/landing-fintech/index.html && echo OK
```

- [ ] **Step 5: Commit**

```bash
git add web/design DEV_HANDOFF.md UI_HANDOFF.md
git status
git commit -m "docs(web): move static comps into web/design/ ahead of app scaffold"
```

(`git status` should show `web/DESIGN.md` etc. as renames, not separate add+delete — confirms `git mv` tracking worked even though we used plain `mv`.)

---

### Task 2: Scaffold the Next.js app

**Files:**
- Create (via CLI): `web/app/package.json`, `web/app/next.config.ts`, `web/app/tsconfig.json`, `web/app/src/app/layout.tsx`, `web/app/src/app/page.tsx`, `web/app/src/app/globals.css`, `web/app/public/*`

**Interfaces:** None yet — this is scaffolding only. Later tasks overwrite `layout.tsx` and `page.tsx`.

- [ ] **Step 1: Run the scaffolder from the repo root**

```bash
npx create-next-app@latest web/app --typescript --eslint --tailwind --app --src-dir --import-alias "@/*" --use-npm
```

All relevant flags are supplied so it should not prompt. If a prompt does appear (CLI version drift), accept the default (press Enter) for each question.

- [ ] **Step 2: Verify the dev server boots**

```bash
cd web/app && npm run dev -- --port 3100 &
sleep 3
curl -sf http://127.0.0.1:3100 > /dev/null && echo "OK: dev server responded"
kill %1
cd ../..
```

- [ ] **Step 3: Add the two env vars the API client will need (Task 3) and commit the example file only**

```bash
cat > web/app/.env.local.example <<'EOF'
# Server-side (RSC, route handlers) base URL for the FastAPI backend.
API_BASE_URL=http://127.0.0.1:8000
# Client-side (browser) base URL — must be duplicated because Next.js only
# inlines NEXT_PUBLIC_ vars, and RSC fetches run in Node, not the browser.
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
EOF
cp web/app/.env.local.example web/app/.env.local
```

`.env.local` is already covered by the `create-next-app` generated `.gitignore` — confirm:

```bash
grep -q "^.env.local\|^.env\*.local" web/app/.gitignore && echo OK
```

- [ ] **Step 4: Commit**

```bash
git add web/app
git status
git commit -m "chore(web): scaffold Next.js app in web/app"
```

---

### Task 3: Typed API client

**Files:**
- Create: `web/app/src/lib/api-client/types.gen.ts` (generated, via script — do not hand-edit)
- Create: `web/app/src/lib/api-client/client.ts`
- Test: `web/app/tests/unit/client.test.ts`
- Modify: `web/app/package.json` (add deps + `generate:api-types` script)

**Interfaces:**
- Produces: `analyzeRun(payload): Promise<{cached: boolean; accepted: RunAccepted}>`, `getRun(id: string): Promise<RunDetail>`, `getRunByTicker(ticker: string, analysisDate: string, profile?: AnalysisProfile): Promise<RunDetail | null>`, `getRunHistory(ticker: string, analysisDate: string, profile?: AnalysisProfile): Promise<RunHistory | null>`, `listRuns(params?: {ticker?: string; limit?: number; offset?: number}): Promise<RunSummary[]>`, classes `ApiError extends Error` (`.status: number`), `RateLimitError extends Error` (`.detail: string`, `.retryAfterSeconds: number`), and re-exported types `RunDetail`, `RunSummary`, `RunHistory`, `RunAccepted`, `Verdict`, `Reports`, `AnalysisProfile`, `RunStatus`.

- [ ] **Step 1: Install dependencies**

```bash
cd web/app
npm install @tanstack/react-query
npm install -D openapi-typescript vitest @testing-library/react @testing-library/jest-dom @vitejs/plugin-react jsdom
cd ../..
```

- [ ] **Step 1.5: Add Vitest config and setup file**

This is needed now, not later: this task's own test (Step 3 below) imports via
the `@/` alias, and Vitest does not read `tsconfig.json` path mappings on its
own — it needs an explicit `resolve.alias`. Creating this file here (rather
than in a later task) is what makes Step 4's test run at all.

`web/app/vitest.config.ts`:

```ts
import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/unit/setup.ts'],
    include: ['tests/unit/**/*.test.{ts,tsx}'],
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
});
```

`web/app/tests/unit/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
```

- [ ] **Step 2: Add the codegen script and generate types**

Add to `web/app/package.json` `"scripts"`:

```json
"generate:api-types": "openapi-typescript ../../api/openapi.json -o src/lib/api-client/types.gen.ts"
```

```bash
cd web/app && npm run generate:api-types && cd ../..
test -f web/app/src/lib/api-client/types.gen.ts && echo OK
```

- [ ] **Step 3: Write the failing test**

`web/app/tests/unit/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { analyzeRun, ApiError, getRun, getRunByTicker, RateLimitError } from '@/lib/api-client/client';

function jsonResponse(body: unknown, init: { status: number; headers?: Record<string, string> }) {
  return new Response(JSON.stringify(body), {
    status: init.status,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
}

describe('analyzeRun', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('marks the result as cached when the server returns 200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ id: 'r1', status: 'completed', poll_url: '/runs/r1', estimated_seconds: 0 }, { status: 200 }),
      ),
    );

    const result = await analyzeRun({ ticker: 'SIEMENS.NS' });

    expect(result.cached).toBe(true);
    expect(result.accepted.id).toBe('r1');
  });

  it('marks the result as not cached when the server returns 202', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ id: 'r2', status: 'queued', poll_url: '/runs/r2', estimated_seconds: 240 }, { status: 202 }),
      ),
    );

    const result = await analyzeRun({ ticker: 'SIEMENS.NS' });

    expect(result.cached).toBe(false);
  });

  it('throws RateLimitError with the server detail and Retry-After on 429', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: 'The service has reached its daily analysis limit.' },
          { status: 429, headers: { 'Retry-After': '3600' } },
        ),
      ),
    );

    await expect(analyzeRun({ ticker: 'SIEMENS.NS' })).rejects.toMatchObject({
      detail: 'The service has reached its daily analysis limit.',
      retryAfterSeconds: 3600,
    });
  });

  it('rejects RateLimitError instances with instanceof', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'limited' }, { status: 429, headers: { 'Retry-After': '60' } })),
    );

    await expect(analyzeRun({ ticker: 'X' })).rejects.toBeInstanceOf(RateLimitError);
  });
});

describe('getRun', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('throws a 404 ApiError when the run does not exist', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Run not found' }, { status: 404 })));

    await expect(getRun('missing')).rejects.toBeInstanceOf(ApiError);
  });
});

describe('getRunByTicker', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns null on 404 instead of throwing (no analysis yet is a normal state)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'not found' }, { status: 404 })));

    await expect(getRunByTicker('SIEMENS.NS', '2026-08-12')).resolves.toBeNull();
  });
});
```

- [ ] **Step 4: Run it to verify it fails**

```bash
cd web/app && npx vitest run tests/unit/client.test.ts
```

Expected: FAIL — `@/lib/api-client/client` does not exist yet.

- [ ] **Step 5: Write `client.ts`**

`web/app/src/lib/api-client/client.ts`:

```ts
import type { components } from './types.gen';

export type RunDetail = components['schemas']['RunDetail'];
export type RunSummary = components['schemas']['RunSummary'];
export type RunHistory = components['schemas']['RunHistory'];
export type RunAccepted = components['schemas']['RunAccepted'];
export type Verdict = components['schemas']['Verdict'];
export type Reports = components['schemas']['Reports'];
export type AnalysisProfile = components['schemas']['AnalysisProfile'];
export type RunStatus = components['schemas']['RunStatus'];

const API_BASE_URL =
  typeof window === 'undefined'
    ? process.env.API_BASE_URL ?? 'http://127.0.0.1:8000'
    : process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Thrown on 429. `detail` is pre-written server copy — render it verbatim,
 * don't write custom error text for it (DEV_HANDOFF.md). */
export class RateLimitError extends Error {
  constructor(public detail: string, public retryAfterSeconds: number) {
    super(detail);
    this.name = 'RateLimitError';
  }
}

export interface AnalyzeResult {
  /** true when the server returned 200 (existing run, free). false means 202
   * (a new run was queued and money was spent). */
  cached: boolean;
  accepted: RunAccepted;
}

export interface AnalyzePayload {
  ticker: string;
  analysis_date?: string;
  profile?: AnalysisProfile;
  force?: boolean;
  refresh_data?: boolean;
}

export async function analyzeRun(payload: AnalyzePayload): Promise<AnalyzeResult> {
  const res = await fetch(`${API_BASE_URL}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (res.status === 429) {
    const body = await res.json().catch(() => ({ detail: 'Rate limited.' }));
    const retryAfterSeconds = Number(res.headers.get('Retry-After') ?? '3600');
    throw new RateLimitError(body.detail ?? 'Rate limited.', retryAfterSeconds);
  }

  if (res.status !== 200 && res.status !== 202) {
    throw new ApiError(res.status, `Unexpected response (${res.status}) from POST /analyze`);
  }

  const accepted = (await res.json()) as RunAccepted;
  return { cached: res.status === 200, accepted };
}

export async function getRun(id: string): Promise<RunDetail> {
  const res = await fetch(`${API_BASE_URL}/runs/${id}`, { cache: 'no-store' });
  if (res.status === 404) throw new ApiError(404, 'Run not found');
  if (!res.ok) throw new ApiError(res.status, `Failed to fetch run ${id}`);
  return (await res.json()) as RunDetail;
}

/** Returns null on 404 — no analysis for that ticker/date/profile is a
 * normal state, not an error (DEV_HANDOFF.md: "POST /analyze to request
 * one"). */
export async function getRunByTicker(
  ticker: string,
  analysisDate: string,
  profile: AnalysisProfile = 'fast',
): Promise<RunDetail | null> {
  const url = `${API_BASE_URL}/runs/${encodeURIComponent(ticker)}/${analysisDate}?profile=${profile}`;
  const res = await fetch(url, { cache: 'no-store' });
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `Failed to fetch ${ticker} ${analysisDate}`);
  return (await res.json()) as RunDetail;
}

export async function getRunHistory(
  ticker: string,
  analysisDate: string,
  profile: AnalysisProfile = 'fast',
): Promise<RunHistory | null> {
  const url = `${API_BASE_URL}/runs/${encodeURIComponent(ticker)}/${analysisDate}/history?profile=${profile}`;
  const res = await fetch(url, { cache: 'no-store' });
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `Failed to fetch history for ${ticker} ${analysisDate}`);
  return (await res.json()) as RunHistory;
}

export async function listRuns(
  params: { ticker?: string; limit?: number; offset?: number } = {},
): Promise<RunSummary[]> {
  const search = new URLSearchParams();
  if (params.ticker) search.set('ticker', params.ticker);
  if (params.limit) search.set('limit', String(params.limit));
  if (params.offset) search.set('offset', String(params.offset));
  const qs = search.toString();

  const res = await fetch(`${API_BASE_URL}/runs${qs ? `?${qs}` : ''}`, { cache: 'no-store' });
  if (!res.ok) throw new ApiError(res.status, 'Failed to list runs');
  return (await res.json()) as RunSummary[];
}
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd web/app && npx vitest run tests/unit/client.test.ts
```

Expected: PASS (all 6 tests).

- [ ] **Step 7: Commit**

```bash
git add web/app/src/lib/api-client web/app/tests/unit/client.test.ts web/app/package.json web/app/package-lock.json
git commit -m "feat(web): typed API client with 200/202/429 branching"
```

---

### Task 4: Null-safe price formatting

**Files:**
- Create: `web/app/src/lib/format.ts`
- Test: `web/app/tests/unit/format.test.ts`

**Interfaces:**
- Produces: `formatPrice(value: number | null | undefined): string`

- [ ] **Step 1: Write the failing test**

`web/app/tests/unit/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { formatPrice } from '@/lib/format';

describe('formatPrice', () => {
  it('renders null as "Not set", never 0', () => {
    expect(formatPrice(null)).toBe('Not set');
  });

  it('renders undefined as "Not set"', () => {
    expect(formatPrice(undefined)).toBe('Not set');
  });

  it('renders an actual zero price as ₹0, not "Not set"', () => {
    expect(formatPrice(0)).toBe('₹0');
  });

  it('formats a decimal price with the rupee sign', () => {
    expect(formatPrice(1234.5)).toBe('₹1,234.5');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd web/app && npx vitest run tests/unit/format.test.ts
```

Expected: FAIL — `@/lib/format` does not exist.

- [ ] **Step 3: Write the implementation**

`web/app/src/lib/format.ts`:

```ts
/**
 * The engine deliberately drops a level it can't make coherent rather than
 * emit a misleading number — a null here is a real answer, not missing data.
 * Rendering it as 0 would be a wrong statement, not a formatting nicety.
 */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Not set';
  return `\u20B9${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd web/app && npx vitest run tests/unit/format.test.ts
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add web/app/src/lib/format.ts web/app/tests/unit/format.test.ts
git commit -m "feat(web): null-safe price formatting (never renders a missing level as 0)"
```

---

### Task 5: TanStack Query provider + polling hook

**Files:**
- Create: `web/app/src/app/providers.tsx`
- Modify: `web/app/src/app/layout.tsx` (wrap `{children}` in `<Providers>`)
- Create: `web/app/src/lib/poll.ts`
- Test: `web/app/tests/unit/poll.test.ts`
(`vitest.config.ts` and `tests/unit/setup.ts` were created in Task 3, Step 1.5 — not touched here)

**Interfaces:**
- Consumes: `getRun` from `@/lib/api-client/client` (Task 3)
- Produces: `usePollRun(runId: string | undefined, initialData?: RunDetail)` — a TanStack Query `useQuery` result whose `refetchInterval` is 4000ms while `status` is `queued`/`running` and stops once `completed`/`failed`.

`vitest.config.ts` and `tests/unit/setup.ts` already exist — created in Task 3,
Step 1.5, because Task 3's own test needed the `@/` alias before this task
ever ran. Nothing to add here.

- [ ] **Step 2: Write the failing test**

`web/app/tests/unit/poll.test.ts`:

```ts
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePollRun } from '@/lib/poll';
import * as client from '@/lib/api-client/client';
import type { RunDetail } from '@/lib/api-client/client';

function makeRun(status: RunDetail['status']): RunDetail {
  return {
    id: 'r1',
    ticker: 'SIEMENS.NS',
    analysis_date: '2026-08-12',
    profile: 'fast',
    status,
    created_at: '2026-08-12T14:26:16Z',
    completed_at: status === 'completed' ? '2026-08-12T14:30:58Z' : null,
    error: null,
    cached: false,
    verdict: null,
    reports: null,
    run_count: 1,
    verdict_is_contested: false,
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe('usePollRun', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps polling every 4s while running, then stops once completed', async () => {
    const getRunSpy = vi
      .spyOn(client, 'getRun')
      .mockResolvedValueOnce(makeRun('running'))
      .mockResolvedValueOnce(makeRun('running'))
      .mockResolvedValueOnce(makeRun('completed'));

    const { result } = renderHook(() => usePollRun('r1'), { wrapper });

    await waitFor(() => expect(getRunSpy).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(4000);
    await waitFor(() => expect(getRunSpy).toHaveBeenCalledTimes(2));

    await vi.advanceTimersByTimeAsync(4000);
    await waitFor(() => expect(getRunSpy).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(result.current.data?.status).toBe('completed'));

    // No further polling once completed.
    await vi.advanceTimersByTimeAsync(10000);
    expect(getRunSpy).toHaveBeenCalledTimes(3);
  });

  it('does not poll when disabled (no run id)', async () => {
    const getRunSpy = vi.spyOn(client, 'getRun');

    renderHook(() => usePollRun(undefined), { wrapper });

    await vi.advanceTimersByTimeAsync(5000);
    expect(getRunSpy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

```bash
cd web/app && npx vitest run tests/unit/poll.test.ts
```

Expected: FAIL — `@/lib/poll` does not exist.

- [ ] **Step 4: Write `poll.ts`**

`web/app/src/lib/poll.ts`:

```ts
'use client';

import { useQuery } from '@tanstack/react-query';
import { getRun, type RunDetail } from './api-client/client';

const TERMINAL_STATUSES: RunDetail['status'][] = ['completed', 'failed'];

export function usePollRun(runId: string | undefined, initialData?: RunDetail) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => getRun(runId as string),
    enabled: Boolean(runId),
    initialData,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && TERMINAL_STATUSES.includes(status)) return false;
      return 4000;
    },
  });
}
```

- [ ] **Step 5: Add the provider and wire it into the layout**

`web/app/src/app/providers.tsx`:

```tsx
'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
```

In `web/app/src/app/layout.tsx`, import `Providers` from `./providers` and wrap the existing `{children}` inside `<body>` with `<Providers>{children}</Providers>`, keeping the rest of the generated file (fonts, metadata) unchanged.

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd web/app && npx vitest run tests/unit/poll.test.ts
```

Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add web/app/src/lib/poll.ts web/app/src/app/providers.tsx web/app/src/app/layout.tsx web/app/vitest.config.ts web/app/tests/unit/setup.ts web/app/tests/unit/poll.test.ts
git commit -m "feat(web): polling hook that stops on completed/failed"
```

---

### Task 6: Run-detail UI components

**Files:**
- Create: `web/app/src/components/RunStatusBanner.tsx`
- Create: `web/app/src/components/VerdictSummary.tsx`
- Create: `web/app/src/components/ReportsAccordion.tsx`
- Create: `web/app/src/components/RunHistoryPanel.tsx`
- Create: `web/app/src/components/RunView.tsx`
- Test: `web/app/tests/unit/components/VerdictSummary.test.tsx`
- Test: `web/app/tests/unit/components/RunHistoryPanel.test.tsx`
- Modify: `web/app/package.json` (add `react-markdown`, `remark-gfm`)

**Interfaces:**
- Consumes: `usePollRun` (Task 5), `getRunHistory` (Task 3), `formatPrice` (Task 4), types `RunDetail`/`Verdict`/`Reports`/`RunHistory` (Task 3)
- Produces: `<RunView initialRun={RunDetail} estimatedSeconds?={number} />` — the single shared component used by both routes in Tasks 8–9.

- [ ] **Step 1: Install markdown rendering deps**

```bash
cd web/app && npm install react-markdown remark-gfm && cd ../..
```

- [ ] **Step 2: Write the failing tests**

`web/app/tests/unit/components/VerdictSummary.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { VerdictSummary } from '@/components/VerdictSummary';
import type { Verdict } from '@/lib/api-client/client';

it('renders null price_target/entry_price/stop_loss as "Not set", not 0', () => {
  const verdict: Verdict = {
    rating: 'Underweight',
    price_target: null,
    time_horizon: '3-6 months',
    levels: { action: 'Hold', entry_price: null, stop_loss: null, position_sizing: null },
  };

  render(<VerdictSummary verdict={verdict} />);

  const notSetCells = screen.getAllByText('Not set');
  expect(notSetCells.length).toBeGreaterThanOrEqual(3);
  expect(screen.queryByText('₹0')).not.toBeInTheDocument();
});

it('renders rating and action as separate values, never collapsed into one', () => {
  const verdict: Verdict = {
    rating: 'Underweight',
    price_target: 500,
    time_horizon: '3-6 months',
    levels: { action: 'Hold', entry_price: 480, stop_loss: 440, position_sizing: '2% of portfolio' },
  };

  render(<VerdictSummary verdict={verdict} />);

  expect(screen.getByText('Underweight')).toBeInTheDocument();
  expect(screen.getByText('Hold')).toBeInTheDocument();
});
```

`web/app/tests/unit/components/RunHistoryPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RunHistoryPanel } from '@/components/RunHistoryPanel';
import type { RunHistory } from '@/lib/api-client/client';

describe('RunHistoryPanel', () => {
  it('renders nothing for a single, uncontested run', () => {
    const history: RunHistory = {
      ticker: 'SIEMENS.NS',
      analysis_date: '2026-08-12',
      profile: 'fast',
      run_count: 1,
      ratings: ['Underweight'],
      verdict_is_contested: false,
      runs: [],
    };

    const { container } = render(<RunHistoryPanel history={history} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('surfaces a contested split instead of hiding it behind the latest run', () => {
    const history: RunHistory = {
      ticker: 'SIEMENS.NS',
      analysis_date: '2026-08-12',
      profile: 'fast',
      run_count: 3,
      ratings: ['Hold', 'Underweight', 'Underweight'],
      verdict_is_contested: true,
      runs: [],
    };

    render(<RunHistoryPanel history={history} />);

    expect(screen.getByText(/Analysed 3 times/)).toBeInTheDocument();
    expect(screen.getByText(/2 said Underweight/)).toBeInTheDocument();
    expect(screen.getByText(/1 said Hold/)).toBeInTheDocument();
    expect(screen.getByText(/disagreed/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify both fail**

```bash
cd web/app && npx vitest run tests/unit/components
```

Expected: FAIL — components don't exist yet.

- [ ] **Step 4: Write the components**

`web/app/src/components/VerdictSummary.tsx`:

```tsx
import { formatPrice } from '@/lib/format';
import type { Verdict } from '@/lib/api-client/client';

export function VerdictSummary({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return null;
  const { rating, price_target, time_horizon, levels } = verdict;

  return (
    <section aria-label="Verdict summary">
      <dl>
        <div>
          <dt>Rating</dt>
          <dd>{rating ?? 'Not set'}</dd>
        </div>
        <div>
          <dt>Action</dt>
          <dd>{levels.action ?? 'Not set'}</dd>
        </div>
        <div>
          <dt>Price target</dt>
          <dd>{formatPrice(price_target)}</dd>
        </div>
        <div>
          <dt>Time horizon</dt>
          <dd>{time_horizon ?? 'Not set'}</dd>
        </div>
        <div>
          <dt>Entry price</dt>
          <dd>{formatPrice(levels.entry_price)}</dd>
        </div>
        <div>
          <dt>Stop loss</dt>
          <dd>{formatPrice(levels.stop_loss)}</dd>
        </div>
        <div>
          <dt>Position sizing</dt>
          <dd>{levels.position_sizing ?? 'Not set'}</dd>
        </div>
      </dl>
      <p>
        Rating and action are independent: a Hold action under an Underweight
        rating means trim, not exit.
      </p>
    </section>
  );
}
```

`web/app/src/components/RunHistoryPanel.tsx`:

```tsx
import type { RunHistory } from '@/lib/api-client/client';

export function RunHistoryPanel({ history }: { history: RunHistory | null }) {
  if (!history || history.run_count <= 1) return null;

  const counts = new Map<string, number>();
  for (const rating of history.ratings) {
    const key = rating ?? 'No rating';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const breakdown = Array.from(counts.entries())
    .map(([rating, count]) => `${count} said ${rating}`)
    .join(', ');

  return (
    <section aria-label="Run history">
      <p>
        Analysed {history.run_count} times — {breakdown}.
      </p>
      {history.verdict_is_contested && (
        <p>
          These runs disagreed. The day&apos;s data was identical, so a split
          rating means the evidence was genuinely balanced — not a bug.
        </p>
      )}
    </section>
  );
}
```

`web/app/src/components/ReportsAccordion.tsx`:

```tsx
'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Reports } from '@/lib/api-client/client';

const REPORT_LABELS: Record<keyof Reports, string> = {
  market: 'Market Analysis',
  sentiment: 'Sentiment Analysis',
  news: 'News Analysis',
  fundamentals: 'Fundamentals Analysis',
  bull_case: 'Bull Case',
  bear_case: 'Bear Case',
  investment_plan: 'Investment Plan',
  trader_plan: 'Trader Plan',
  risk_debate: 'Risk Debate',
  final_decision: 'Final Decision',
};

// Conclusion first, then evidence — final_decision opens by default so a
// reader sees a landing summary without needing to expand ten sections.
const REPORT_ORDER: (keyof Reports)[] = [
  'final_decision',
  'investment_plan',
  'bull_case',
  'bear_case',
  'trader_plan',
  'risk_debate',
  'market',
  'sentiment',
  'news',
  'fundamentals',
];

export function ReportsAccordion({ reports }: { reports: Reports | null }) {
  if (!reports) return null;

  const sections = REPORT_ORDER.filter((key) => reports[key]);
  if (sections.length === 0) return null;

  return (
    <section aria-label="Analyst reports">
      {sections.map((key, index) => (
        <details key={key} open={index === 0}>
          <summary>{REPORT_LABELS[key]}</summary>
          <div>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{reports[key] as string}</ReactMarkdown>
          </div>
        </details>
      ))}
    </section>
  );
}
```

`web/app/src/components/RunStatusBanner.tsx`:

```tsx
'use client';

import { useEffect, useState } from 'react';
import type { RunDetail } from '@/lib/api-client/client';

export function RunStatusBanner({
  run,
  estimatedSeconds,
}: {
  run: RunDetail;
  estimatedSeconds?: number;
}) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (run.status !== 'queued' && run.status !== 'running') return;
    const startedAt = Date.parse(run.created_at);
    const tick = () => setElapsedSeconds(Math.max(0, Math.round((Date.now() - startedAt) / 1000)));
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [run.status, run.created_at]);

  if (run.status === 'failed') {
    return (
      <div role="alert">
        <p>This analysis failed.</p>
        <p>{run.error ?? 'No error detail was recorded.'}</p>
      </div>
    );
  }

  if (run.status === 'completed') {
    return null;
  }

  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  const estimateText = estimatedSeconds
    ? ` (estimated ~${Math.round(estimatedSeconds / 60)} min — a rough guide, not a promise)`
    : '';

  return (
    <div role="status" aria-live="polite">
      <p>
        {run.status === 'queued' ? 'Queued' : 'Running'} — {minutes}m {seconds}s elapsed
        {estimateText}
      </p>
      <p>This can take 4 to 14 minutes. You can leave this page and come back — the link stays valid.</p>
    </div>
  );
}
```

`web/app/src/components/RunView.tsx`:

```tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import { getRunHistory, type RunDetail } from '@/lib/api-client/client';
import { usePollRun } from '@/lib/poll';
import { ReportsAccordion } from './ReportsAccordion';
import { RunHistoryPanel } from './RunHistoryPanel';
import { RunStatusBanner } from './RunStatusBanner';
import { VerdictSummary } from './VerdictSummary';

export function RunView({
  initialRun,
  estimatedSeconds,
}: {
  initialRun: RunDetail;
  estimatedSeconds?: number;
}) {
  const { data: run } = usePollRun(initialRun.id, initialRun);
  const current = run ?? initialRun;

  const historyQuery = useQuery({
    queryKey: ['history', current.ticker, current.analysis_date, current.profile],
    queryFn: () => getRunHistory(current.ticker, current.analysis_date, current.profile),
    enabled: current.status === 'completed',
  });

  return (
    <div>
      <RunStatusBanner run={current} estimatedSeconds={estimatedSeconds} />
      {current.status === 'completed' && (
        <>
          <VerdictSummary verdict={current.verdict} />
          <RunHistoryPanel history={historyQuery.data ?? null} />
          <ReportsAccordion reports={current.reports} />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd web/app && npx vitest run tests/unit/components
```

Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add web/app/src/components web/app/tests/unit/components web/app/package.json web/app/package-lock.json
git commit -m "feat(web): run-detail components (verdict, reports, status, history)"
```

---

### Task 7: Home page — search + recent runs

**Files:**
- Create: `web/app/src/components/SearchForm.tsx`
- Create: `web/app/src/components/RecentRuns.tsx`
- Modify: `web/app/src/app/page.tsx`
- Test: `web/app/tests/unit/SearchForm.test.tsx`

**Interfaces:**
- Consumes: `analyzeRun`, `RateLimitError`, `listRuns`, `RunSummary` (Task 3)
- Produces: navigation to `/runs/{id}?cached=0|1` on submit (consumed by Task 8's route, which may ignore the query param or use it for an ephemeral banner)

- [ ] **Step 1: Write the failing test**

`web/app/tests/unit/SearchForm.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SearchForm } from '@/components/SearchForm';
import { RateLimitError } from '@/lib/api-client/client';

const pushMock = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/lib/api-client/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client/client')>();
  return { ...actual, analyzeRun: vi.fn() };
});

import { analyzeRun } from '@/lib/api-client/client';

describe('SearchForm', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('navigates to the run with cached=1 on a 200 (existing) response', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r1', status: 'completed', poll_url: '/runs/r1', estimated_seconds: 0 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'SIEMENS.NS');
    await userEvent.click(screen.getByRole('button', { name: /Analyse/ }));

    expect(pushMock).toHaveBeenCalledWith('/runs/r1?cached=1');
  });

  it('navigates to the run with cached=0 on a 202 (new) response', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: false,
      accepted: { id: 'r2', status: 'queued', poll_url: '/runs/r2', estimated_seconds: 240 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'RELIANCE');
    await userEvent.click(screen.getByRole('button', { name: /Analyse/ }));

    expect(pushMock).toHaveBeenCalledWith('/runs/r2?cached=0');
  });

  it('shows the server rate-limit message and does not navigate on 429', async () => {
    vi.mocked(analyzeRun).mockRejectedValue(new RateLimitError('Daily limit reached.', 3600));

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'SIEMENS.NS');
    await userEvent.click(screen.getByRole('button', { name: /Analyse/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Daily limit reached.');
    expect(screen.getByRole('alert')).toHaveTextContent('Existing analyses are still available');
    expect(pushMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd web/app && npx vitest run tests/unit/SearchForm.test.tsx
```

Expected: FAIL — `@/components/SearchForm` does not exist. (Also install `@testing-library/user-event`: `npm install -D @testing-library/user-event`.)

- [ ] **Step 3: Write `SearchForm.tsx`**

`web/app/src/components/SearchForm.tsx`:

```tsx
'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { analyzeRun, RateLimitError } from '@/lib/api-client/client';

export function SearchForm() {
  const router = useRouter();
  const [ticker, setTicker] = useState('');
  const [profile, setProfile] = useState<'fast' | 'detailed'>('fast');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!ticker.trim()) return;

    setSubmitting(true);
    setErrorMessage(null);

    try {
      const { accepted, cached } = await analyzeRun({ ticker, profile });
      router.push(`/runs/${accepted.id}?cached=${cached ? '1' : '0'}`);
    } catch (error) {
      if (error instanceof RateLimitError) {
        setErrorMessage(`${error.detail} Existing analyses are still available to read — see recent runs below.`);
      } else {
        setErrorMessage('Something went wrong requesting this analysis. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Request an analysis">
      <label htmlFor="ticker-input">Ticker (NSE/BSE)</label>
      <input
        id="ticker-input"
        name="ticker"
        value={ticker}
        onChange={(event) => setTicker(event.target.value)}
        placeholder="RELIANCE or SIEMENS.NS"
        maxLength={32}
        required
      />
      <fieldset>
        <legend>Profile</legend>
        <label>
          <input
            type="radio"
            name="profile"
            value="fast"
            checked={profile === 'fast'}
            onChange={() => setProfile('fast')}
          />
          Fast (~4 min)
        </label>
        <label>
          <input
            type="radio"
            name="profile"
            value="detailed"
            checked={profile === 'detailed'}
            onChange={() => setProfile('detailed')}
          />
          Detailed (~14 min)
        </label>
      </fieldset>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Requesting…' : 'Analyse'}
      </button>
      {errorMessage && <div role="alert">{errorMessage}</div>}
    </form>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd web/app && npx vitest run tests/unit/SearchForm.test.tsx
```

Expected: PASS (3 tests).

- [ ] **Step 5: Write `RecentRuns.tsx` and wire up `page.tsx` (no dedicated test — pure presentational list + Server Component composition, covered end-to-end by Task 11)**

`web/app/src/components/RecentRuns.tsx`:

```tsx
import Link from 'next/link';
import type { RunSummary } from '@/lib/api-client/client';

export function RecentRuns({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) {
    return <p>No analyses yet.</p>;
  }

  return (
    <section aria-label="Recent runs">
      <h2>Recent analyses</h2>
      <ul>
        {runs.map((run) => (
          <li key={run.id}>
            <Link href={`/runs/${run.id}`}>
              {run.ticker} — {run.analysis_date} — {run.status}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

Replace the generated content of `web/app/src/app/page.tsx` with:

```tsx
import { listRuns } from '@/lib/api-client/client';
import { RecentRuns } from '@/components/RecentRuns';
import { SearchForm } from '@/components/SearchForm';

export default async function HomePage() {
  const recentRuns = await listRuns({ limit: 10 });

  return (
    <main>
      <h1>TradingAgents — Indian Equity Research</h1>
      <p>
        Research, not advice. Every analysis returns full evidence — the bull
        case, the bear case, and the numbers — not just a rating.
      </p>
      <SearchForm />
      <RecentRuns runs={recentRuns} />
    </main>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add web/app/src/components/SearchForm.tsx web/app/src/components/RecentRuns.tsx web/app/src/app/page.tsx web/app/tests/unit/SearchForm.test.tsx web/app/package.json web/app/package-lock.json
git commit -m "feat(web): home page with search form and recent runs"
```

---

### Task 8: `/runs/[id]` durable-link route

**Files:**
- Create: `web/app/src/app/runs/[id]/page.tsx`

**Interfaces:**
- Consumes: `getRun`, `ApiError` (Task 3), `<RunView>` (Task 6)

- [ ] **Step 1: Write the route**

`web/app/src/app/runs/[id]/page.tsx`:

```tsx
import { notFound } from 'next/navigation';
import { ApiError, getRun } from '@/lib/api-client/client';
import { RunView } from '@/components/RunView';

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let run;
  try {
    run = await getRun(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <main>
      <h1>
        {run.ticker} — {run.analysis_date}
      </h1>
      <RunView initialRun={run} />
    </main>
  );
}
```

- [ ] **Step 2: Manual smoke check against a running dev server (no backend needed yet — this only confirms the route doesn't crash on a network error)**

```bash
cd web/app && npm run dev -- --port 3100 &
sleep 3
curl -s http://127.0.0.1:3100/runs/nonexistent-id -o /dev/null -w "%{http_code}\n"
kill %1
cd ../..
```

Expected: `500` is acceptable here only if `API_BASE_URL` has nothing listening (connection refused surfaces as a thrown error, not a 404) — this step just confirms the route compiles and renders without a build error. Full behavior (real 404, real success) is verified in Task 11 (mocked) and Task 12 (live backend).

- [ ] **Step 3: Commit**

```bash
git add "web/app/src/app/runs"
git commit -m "feat(web): durable /runs/[id] route"
```

---

### Task 9: `/stock/[ticker]/[date]` canonical route

**Files:**
- Create: `web/app/src/app/stock/[ticker]/[date]/page.tsx`

**Interfaces:**
- Consumes: `getRunByTicker` (Task 3), `<RunView>` (Task 6)

- [ ] **Step 1: Write the route**

`web/app/src/app/stock/[ticker]/[date]/page.tsx`:

```tsx
import Link from 'next/link';
import { getRunByTicker } from '@/lib/api-client/client';
import { RunView } from '@/components/RunView';

export default async function StockPage({
  params,
}: {
  params: Promise<{ ticker: string; date: string }>;
}) {
  const { ticker, date } = await params;
  const decodedTicker = decodeURIComponent(ticker);
  const run = await getRunByTicker(decodedTicker, date);

  if (!run) {
    return (
      <main>
        <h1>
          {decodedTicker} — {date}
        </h1>
        <p>No analysis exists yet for this ticker and date.</p>
        <Link href={`/?ticker=${encodeURIComponent(decodedTicker)}&date=${date}`}>Request an analysis</Link>
      </main>
    );
  }

  return (
    <main>
      <h1>
        {run.ticker} — {run.analysis_date}
      </h1>
      <RunView initialRun={run} />
    </main>
  );
}
```

- [ ] **Step 2: Build to confirm the route compiles**

```bash
cd web/app && npm run build
cd ../..
```

Expected: build succeeds with the two new dynamic routes listed in the output.

- [ ] **Step 3: Commit**

```bash
git add "web/app/src/app/stock"
git commit -m "feat(web): canonical /stock/[ticker]/[date] route"
```

---

### Task 10: E2E mock API server + fixtures

**Files:**
- Create: `web/app/tests/e2e/mock-server.ts`
- Create: `web/app/tests/e2e/fixtures/completed.json` (copy of `api/fixtures/sample_run.json`)
- Create: `web/app/tests/e2e/fixtures/contested-history.json`
- Modify: `web/app/package.json` (add `tsx`, `@playwright/test`)

**Interfaces:**
- Produces: an HTTP server on `127.0.0.1:8010` implementing `POST /analyze`, `GET /runs/:id`, `GET /runs/:ticker/:date`, `GET /runs/:ticker/:date/history`, `GET /runs`, matching the shapes in `api/schemas.py`. Used by Task 11's Playwright config.

This exists so E2E tests never depend on the live Python backend/worker — they're deterministic and free to run (`DEV_HANDOFF.md`'s "Offline dev without the backend running" applies to automated tests too, not just manual UI iteration).

- [ ] **Step 1: Install test deps**

```bash
cd web/app && npm install -D @playwright/test tsx && npx playwright install chromium && cd ../..
```

- [ ] **Step 2: Copy the real fixture and hand-write the contested-history one**

```bash
mkdir -p web/app/tests/e2e/fixtures
cp api/fixtures/sample_run.json web/app/tests/e2e/fixtures/completed.json
```

`web/app/tests/e2e/fixtures/contested-history.json`:

```json
{
  "ticker": "SIEMENS.NS",
  "analysis_date": "2026-08-12",
  "profile": "fast",
  "run_count": 3,
  "ratings": ["Hold", "Underweight", "Underweight"],
  "verdict_is_contested": true,
  "runs": [
    {
      "id": "run-3",
      "ticker": "SIEMENS.NS",
      "analysis_date": "2026-08-12",
      "profile": "fast",
      "status": "completed",
      "created_at": "2026-08-14T10:00:00Z",
      "completed_at": "2026-08-14T10:05:00Z",
      "error": null,
      "cached": false
    },
    {
      "id": "run-2",
      "ticker": "SIEMENS.NS",
      "analysis_date": "2026-08-12",
      "profile": "fast",
      "status": "completed",
      "created_at": "2026-08-13T10:00:00Z",
      "completed_at": "2026-08-13T10:05:00Z",
      "error": null,
      "cached": false
    },
    {
      "id": "run-completed",
      "ticker": "SIEMENS.NS",
      "analysis_date": "2026-08-12",
      "profile": "fast",
      "status": "completed",
      "created_at": "2026-08-12T14:26:16Z",
      "completed_at": "2026-08-12T14:30:58Z",
      "error": null,
      "cached": false
    }
  ]
}
```

- [ ] **Step 3: Write the mock server**

`web/app/tests/e2e/mock-server.ts`:

```ts
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = 8010;
const PROGRESSIVE_ID = 'run-progressive';

const completedFixture = JSON.parse(
  readFileSync(path.join(__dirname, 'fixtures', 'completed.json'), 'utf-8'),
);
const contestedHistoryFixture = JSON.parse(
  readFileSync(path.join(__dirname, 'fixtures', 'contested-history.json'), 'utf-8'),
);

const runs = new Map<string, Record<string, unknown>>();
runs.set('run-completed', completedFixture);
runs.set('run-failed', {
  id: 'run-failed',
  ticker: 'FAILCO.NS',
  analysis_date: '2026-08-16',
  profile: 'fast',
  status: 'failed',
  created_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
  error: 'The market data provider timed out after 3 retries.',
  cached: false,
  verdict: null,
  reports: null,
  run_count: 1,
  verdict_is_contested: false,
});

// A run that answers queued -> running -> completed across successive polls,
// so the E2E test can assert the UI actually reflects live status changes.
let progressivePollCount = 0;
function progressiveRun() {
  progressivePollCount += 1;
  if (progressivePollCount === 1) {
    return { ...completedFixture, id: PROGRESSIVE_ID, status: 'queued', verdict: null, reports: null, completed_at: null };
  }
  if (progressivePollCount === 2) {
    return { ...completedFixture, id: PROGRESSIVE_ID, status: 'running', verdict: null, reports: null, completed_at: null };
  }
  return { ...completedFixture, id: PROGRESSIVE_ID };
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://localhost:${PORT}`);
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (req.method === 'POST' && url.pathname === '/analyze') {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    const body = JSON.parse(Buffer.concat(chunks).toString('utf-8') || '{}');

    if (body.ticker === 'RATELIMIT') {
      res.statusCode = 429;
      res.setHeader('Retry-After', '3600');
      res.end(
        JSON.stringify({
          detail:
            'You have requested 10 analyses today, which is the limit of 10. Previously completed analyses are still available to read.',
        }),
      );
      return;
    }

    if (body.ticker === 'PROGRESS') {
      progressivePollCount = 0;
      res.statusCode = 202;
      res.end(
        JSON.stringify({ id: PROGRESSIVE_ID, status: 'queued', poll_url: `/runs/${PROGRESSIVE_ID}`, estimated_seconds: 8 }),
      );
      return;
    }

    res.statusCode = 202;
    res.end(JSON.stringify({ id: 'run-completed', status: 'queued', poll_url: '/runs/run-completed', estimated_seconds: 240 }));
    return;
  }

  const historyMatch = url.pathname.match(/^\/runs\/([^/]+)\/([^/]+)\/history$/);
  if (req.method === 'GET' && historyMatch) {
    res.end(JSON.stringify(contestedHistoryFixture));
    return;
  }

  const runIdMatch = url.pathname.match(/^\/runs\/([^/]+)$/);
  if (req.method === 'GET' && runIdMatch) {
    const id = runIdMatch[1];
    if (id === PROGRESSIVE_ID) {
      res.end(JSON.stringify(progressiveRun()));
      return;
    }
    const run = runs.get(id);
    if (!run) {
      res.statusCode = 404;
      res.end(JSON.stringify({ detail: 'Run not found' }));
      return;
    }
    res.end(JSON.stringify(run));
    return;
  }

  const byTickerMatch = url.pathname.match(/^\/runs\/([^/]+)\/([^/]+)$/);
  if (req.method === 'GET' && byTickerMatch) {
    const [, ticker] = byTickerMatch;
    const run = [...runs.values()].find((entry) => entry.ticker === ticker);
    if (!run) {
      res.statusCode = 404;
      res.end(JSON.stringify({ detail: 'No analysis for that ticker and date.' }));
      return;
    }
    res.end(JSON.stringify(run));
    return;
  }

  if (req.method === 'GET' && url.pathname === '/runs') {
    const summaries = [...runs.values()].map(
      ({ id, ticker, analysis_date, profile, status, created_at, completed_at, error, cached }) => ({
        id,
        ticker,
        analysis_date,
        profile,
        status,
        created_at,
        completed_at,
        error,
        cached,
      }),
    );
    res.end(JSON.stringify(summaries));
    return;
  }

  res.statusCode = 404;
  res.end(JSON.stringify({ detail: 'Not found' }));
});

server.listen(PORT, () => {
  console.log(`Mock API listening on http://127.0.0.1:${PORT}`);
});
```

- [ ] **Step 4: Verify it runs standalone**

```bash
cd web/app
npx tsx tests/e2e/mock-server.ts &
sleep 1
curl -s http://127.0.0.1:8010/runs | head -c 200
echo
curl -s -X POST http://127.0.0.1:8010/analyze -H "Content-Type: application/json" -d '{"ticker":"RATELIMIT"}' -w "\n%{http_code}\n"
kill %1
cd ../..
```

Expected: first curl prints a JSON array containing `run-completed` and `run-failed`; second prints the rate-limit `detail` body followed by `429`.

- [ ] **Step 5: Commit**

```bash
git add web/app/tests/e2e/mock-server.ts web/app/tests/e2e/fixtures web/app/package.json web/app/package-lock.json
git commit -m "test(web): E2E mock API server and fixtures"
```

---

### Task 11: Playwright E2E specs

**Files:**
- Create: `web/app/playwright.config.ts`
- Create: `web/app/tests/e2e/search-to-result.spec.ts`
- Create: `web/app/tests/e2e/failed-run.spec.ts`
- Create: `web/app/tests/e2e/contested-history.spec.ts`
- Create: `web/app/tests/e2e/rate-limit.spec.ts`
- Modify: `web/app/package.json` (add `test:e2e` script)

**Interfaces:** Consumes the mock server from Task 10 and the full app from Tasks 6–9. This task is the automated stand-in for 5 of the 6 items in `DEV_HANDOFF.md`'s "Before calling anything done" checklist (the 6th — real queued→running→completed against the live worker — is Task 12, manual).

- [ ] **Step 1: Write the Playwright config**

`web/app/playwright.config.ts`:

```ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:3100',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'npx tsx tests/e2e/mock-server.ts',
      port: 8010,
      reuseExistingServer: false,
      timeout: 15000,
    },
    {
      command: 'npm run dev -- --port 3100',
      port: 3100,
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        API_BASE_URL: 'http://127.0.0.1:8010',
        NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:8010',
      },
    },
  ],
});
```

Add to `web/app/package.json` `"scripts"`: `"test:e2e": "playwright test"`.

- [ ] **Step 2: Write the specs**

`web/app/tests/e2e/search-to-result.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

test('search queues a run and shows the verdict once it completes', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Ticker (NSE/BSE)').fill('PROGRESS');
  await page.getByRole('button', { name: 'Analyse' }).click();

  await expect(page).toHaveURL(/\/runs\/run-progressive/);
  await expect(page.getByRole('status')).toContainText(/Queued|Running/);

  await expect(page.getByText('Underweight')).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('status')).toHaveCount(0);
});
```

`web/app/tests/e2e/failed-run.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

test('a failed run shows its error plainly and does not spin', async ({ page }) => {
  await page.goto('/runs/run-failed');

  await expect(page.getByRole('alert')).toContainText('The market data provider timed out');
  await expect(page.getByRole('status')).toHaveCount(0);
});
```

`web/app/tests/e2e/contested-history.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

test('a contested verdict is surfaced, not hidden behind the latest rating', async ({ page }) => {
  await page.goto('/runs/run-completed');

  await expect(page.getByText(/Analysed 3 times/)).toBeVisible();
  await expect(page.getByText(/disagreed/)).toBeVisible();
});
```

`web/app/tests/e2e/rate-limit.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

test('a 429 shows the server message, and cached reads keep working', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Ticker (NSE/BSE)').fill('RATELIMIT');
  await page.getByRole('button', { name: 'Analyse' }).click();

  await expect(page.getByRole('alert')).toContainText('limit of 10');
  await expect(page.getByRole('alert')).toContainText('Existing analyses are still available');

  await page.getByRole('link', { name: /SIEMENS.NS/ }).click();
  await expect(page).toHaveURL(/\/runs\/run-completed/);
  await expect(page.getByText('Underweight')).toBeVisible();
});
```

- [ ] **Step 3: Run the suite**

```bash
cd web/app && npx playwright test
cd ../..
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add web/app/playwright.config.ts "web/app/tests/e2e" web/app/package.json
git commit -m "test(web): E2E coverage for search, failure, contested history, rate limiting"
```

---

### Task 12: Manual verification against the live backend

**Files:** None — this task runs the app against the real API and worker and is not automatable (it costs real LLM money and requires two long-running local processes this plan doesn't control).

This directly executes `DEV_HANDOFF.md`'s "Before calling anything done" checklist against the real system, one item per step. Do this once, by hand, before considering the integration done.

- [ ] **Step 1: Start both backend processes from the repo root**

```bash
"E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe" -m uvicorn api.main:app --reload
```

In a second terminal:

```bash
"E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe" -m api.worker
```

- [ ] **Step 2: Start the app pointed at the real backend**

```bash
cd web/app
cat .env.local  # confirm API_BASE_URL / NEXT_PUBLIC_API_BASE_URL both point at 127.0.0.1:8000
npm run dev
```

- [ ] **Step 3: Confirm a queued run actually transitions (worker is live)**

In the browser, submit a ticker not analysed before today (e.g. a real NSE symbol). Confirm the `/runs/[id]` page shows `queued` → `running` → `completed` without manual refresh, and that reports/verdict render once complete.

- [ ] **Step 4: Confirm `POST /analyze` branches correctly on both status codes**

Submit the **same** ticker + today's date again (no `force`). Confirm this returns instantly (200/cached) and the UI does not show a new queued state — it should land straight on the completed run. Do **not** use `force: true` here; a second distinct ticker instead of repeating with `force` avoids spending money twice.

- [ ] **Step 5: Confirm 429 behavior using the real per-IP cap**

Either exhaust the 10/day per-IP cap for real, or temporarily lower `TRADINGAGENTS_API_ALLOWED_ORIGINS`'s sibling setting `max_runs_per_ip_per_day` via env (`TRADINGAGENTS_API_MAX_RUNS_PER_IP_PER_DAY=1` before starting `uvicorn`) to hit it quickly. Confirm the UI renders the server's `detail` text and that `GET /runs` / existing `/runs/[id]` pages still load normally while blocked.

- [ ] **Step 6: Confirm null levels render as "Not set", not 0**

Find or produce a completed run where `verdict.price_target`/`entry_price`/`stop_loss` are null (the SIEMENS.NS fixture is one such real example). Confirm the results page shows "Not set" for each, never `₹0` or blank.

- [ ] **Step 7: Confirm long reports don't dump into one scroll**

On a completed run, confirm the 10 report sections render as separate collapsible `<details>` blocks, with only `final_decision` open by default.

- [ ] **Step 8: Record the outcome**

If every step above passes, the integration matches `DEV_HANDOFF.md`'s definition of done. This step has no code to commit — it's a verification gate, not a deliverable.

---

## Self-Review Notes

- **Spec coverage:** All four "Suggested first screens" from `DEV_HANDOFF.md` are covered — search/home (Task 7), stock/results (Tasks 8–9), in-progress (Task 6's `RunStatusBanner` + polling), history (Task 6's `RunHistoryPanel`). All six "Before calling anything done" checklist items are covered — five automated in Task 11, the sixth (live worker transition) in Task 12.
- **Placeholder scan:** No TBD/TODO markers; every step has runnable commands or complete code.
- **Type consistency:** `RunDetail`, `RunSummary`, `RunHistory`, `RunAccepted`, `Verdict`, `Reports`, `AnalysisProfile`, `RunStatus` are defined once in Task 3 (`client.ts`, aliased from generated `types.gen.ts`) and imported by that exact name in every later task — no renames across tasks. `usePollRun`'s signature (Task 5) matches its only call site in `RunView` (Task 6). `formatPrice`'s signature (Task 4) matches its call sites in `VerdictSummary` (Task 6).
