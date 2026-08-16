# Dev Handoff — Frontend + Backend Integration

Written 2026-08-16 for a fresh Claude Code session picking up implementation.
Design work (visual direction, tokens, motion) is intentionally out of scope
here — see `web/design/DESIGN.md` if you need it, but this doc is about wiring a
real app to a real API. Read `UI_HANDOFF.md` too; it's the deeper source for
the API contract and this doc doesn't repeat everything in it.

## What you're building

A web frontend for a multi-agent equity-research tool covering Indian
markets (NSE/BSE). A user types a ticker, requests an analysis, waits
4–14 minutes, and reads what four analysts, a bull/bear debate, a trader,
and a three-way risk panel concluded.

**Frame as research, not advice.** Evidence above verdict — the API
deliberately returns full reports, not just a rating. SEBI-sensitive as a
public India-facing tool.

## Boundaries

- **Do not edit `tradingagents/`, `api/`, or `cli/`.** Another session owns
  the backend. If you need an API change, ask rather than making it.
- Build in `web/` (or wherever the new app scaffold lands — see "Open
  decisions" below).
- **Never add `Co-Authored-By: Claude` or any AI attribution** to commits or
  PR bodies. Standing rule for this repo.

## Environment — a real gotcha

**This worktree (`TradingAgents_Ind-ui-worktree`) has no `.venv` of its
own.** The Python environment lives in the sibling main repo:

```
E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe
```

Verified present; the worktree's own `.venv` path does not exist. Use the
main repo's venv for both processes below, run from this worktree's root.

Two processes, both required:

```bash
# terminal 1 — the API
"E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe" -m uvicorn api.main:app --reload

# terminal 2 — the worker that actually runs analyses
"E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe" -m api.worker
```

API at `http://127.0.0.1:8000`, interactive docs at `/docs`. **Without the
worker running, nothing executes** — requests sit at `queued` forever. That
is expected, not a bug — check for it before assuming something's broken.

CORS allows `http://localhost:3000` by default (`api/settings.py`,
`allowed_origins`). Other dev ports need
`TRADINGAGENTS_API_ALLOWED_ORIGINS` set as an env var.

Backend data lives in SQLite at `~/.tradingagents/api.db`. Delete it for a
clean slate.

## The API contract

`api/openapi.json` is the generated spec — import it for a typed client.
**It understates two real behaviors** (confirmed by reading `api/main.py`,
`api/ratelimit.py`, `api/settings.py` directly, not just the spec):

1. `POST /analyze` can return **200** (existing run, instant, free) as well
   as the **202** the spec documents (new run queued). Branch on status
   code, not just body shape.
2. **429** isn't in the spec at all, but is real — `api/ratelimit.py`
   raises it via `BudgetExceeded`. Body is FastAPI's default shape:
   `{"detail": "<message>"}`, plus a `Retry-After` header (seconds). Three
   distinct causes, each with its own pre-written message — **render
   `detail` directly rather than writing your own copy**, they're already
   good UX text:
   - kill switch active (operator-triggered stop)
   - global daily cap hit (default 500 runs/day)
   - per-IP daily cap hit (default 10 runs/day)

   **Cached reads are never blocked** by any of these — a rate-limited user
   can still read existing analyses. Say that in the error UI; don't show a
   dead end.

| Method | Path | Purpose |
|---|---|---|
| POST | `/analyze` | queue an analysis, or get the existing one |
| GET | `/runs/{id}` | poll one run |
| GET | `/runs/{ticker}/{date}` | what a stock page asks for |
| GET | `/runs/{ticker}/{date}/history` | compare repeat runs |
| GET | `/runs` | list, filter by ticker (`limit` ≤100, `offset`) |
| GET | `/health` | dependency status |

### POST /analyze request

```json
{ "ticker": "SIEMENS.NS", "analysis_date": "2026-08-12",
  "profile": "fast", "force": false, "refresh_data": false }
```

- Only `ticker` required (max 32 chars). `analysis_date` defaults to today.
- **Tickers normalize server-side** — `reliance` and `RELIANCE.NS ` hit the
  same cache entry. Don't normalize client-side.
- **Cache key is `(ticker, analysis_date, profile)`.** A repeat request for
  the same three returns the existing run, not a new one.
- `profile`: `fast` (~4 min) or `detailed` (~14 min). Both fetch identical
  data — `fast` just runs analysts concurrently with 1 debate round.
- `force: true`: run fresh anyway. **Old run is kept, not replaced** —
  results accumulate for comparison. **Do not hammer this while
  developing** — it costs real LLM money. Repeat the same
  ticker+date+profile without `force` instead; that's free.
- `refresh_data: true`: also re-fetch news/filings instead of replaying the
  day's snapshot. Implies `force`.

### Run shape

`status`: `queued` | `running` | `completed` | `failed`.
`verdict` and `reports` are **null until `completed`**.

**`verdict`** — every field nullable, null is normal, not an error state:
- `rating`: 5-tier — Buy / Overweight / Hold / Underweight / Sell
- `price_target`, `time_horizon`
- `levels.action`: **separate 3-tier field** — Buy / Hold / Sell. Can
  legitimately differ from `rating`: a `Hold` action under an `Underweight`
  rating means "trim, don't exit." Don't collapse these into one badge.
- `levels.entry_price`, `levels.stop_loss`, `levels.position_sizing`

**Never render a missing level as `0` or `"—0"`.** The engine deliberately
drops a stop-loss it can't make coherent rather than emit a misleading
number. In a real observed run, `price_target`/`entry_price`/`stop_loss`
were all null while `rating` and `action` were populated — that's correct,
not incomplete. Render "Not set."

**`reports`** — ten optional markdown strings: `market`, `sentiment`,
`news`, `fundamentals`, `bull_case`, `bear_case`, `investment_plan`,
`trader_plan`, `risk_debate`, `final_decision`. A real run totals ~11,375
words, `sentiment` the largest (~3,000). **Plan for long content** —
collapsible sections or tabs, not one scroll. Markdown includes tables and
₹ amounts; use a real renderer.

**`RunHistory`** (`GET /runs/{ticker}/{date}/history`): `run_count`,
`ratings` (array, newest first, nullable entries), `verdict_is_contested`
(bool — true when repeat runs of the *same* day's snapshot reached
different ratings; the data was identical, so a split means the evidence
is genuinely balanced, not a bug). Surface this, don't hide it: *"Analysed
3 times — 2 said Underweight, 1 said Hold."*

## Offline dev without the backend running

`api/fixtures/sample_run.json` is a real completed run (SIEMENS.NS, rating
Underweight, `run_count: 1`, `verdict_is_contested: false`) matching the
`RunDetail` schema exactly. Use it for UI work that doesn't need live
polling — most of the results view can be built and iterated against this
fixture alone, without spending an analysis. Word counts per report are
documented in `UI_HANDOFF.md` and match this fixture precisely if you need
to sanity-check a renderer against real lengths.

## The three functional problems that actually matter

These are product requirements, not visual choices — whatever the UI looks
like, it needs to solve these:

1. **The wait is 4–14 minutes.** Poll `GET /runs/{id}` every few seconds.
   `estimated_seconds` in the 202 body is a rough guide, not a promise. The
   run id is a durable link — decide whether the wait is a screen the user
   sits on or one they can leave and come back to (their call, but the API
   supports either).
2. **Repeat runs can disagree** (`verdict_is_contested` / `run_count` /
   `/history`). Must be surfaced, not hidden behind whichever ran last.
3. **Failure is real.** `status: failed` carries an `error` string. Show it
   plainly — don't spin forever on a run that already died.

## What already exists (reference, not a build target)

`web/design/landing-fintech/index.html` and `web/design/research/index.html` are static,
framework-free HTML comps — no build step, single self-contained files.
They're useful for **understanding what data appears where** (the research
page renders the full `RunDetail` shape faithfully against the fixture
above, agent-by-agent), but they are not the app you're building and
shouldn't be mistaken for a starting scaffold — there's no `package.json`
anywhere in this repo yet. `web/design/DESIGN.md` documents their visual system if
design work becomes in-scope later; skip it otherwise.

## Open decisions for you to make explicitly

Nothing below is decided. Say what you're choosing and why before building:

- **Stack.** Not decided. Next.js is the suggested default (API is plain
  REST + OpenAPI, so anything works). No scaffold exists yet.
- **The wait screen's persistence model** (sit-and-wait vs. leave-and-return
  via the durable run id) — affects routing.

### Recommended repo structure

Not yet executed — proposed shape, pick this or state a different one before
scaffolding. Backend paths (`tradingagents/`, `api/`, `cli/`) are fixed and
off-limits regardless of what you choose here.

```
TradingAgents_Ind-ui-worktree/
├── tradingagents/          # engine — don't touch
├── api/                    # FastAPI service — don't touch
├── cli/                    # terminal client — don't touch
├── web/
│   ├── design/              # ← the static comps, moved here (complete)
│   │   ├── DESIGN.md
│   │   ├── landing-fintech/index.html
│   │   ├── landing/index.html         (abandoned direction)
│   │   └── research/index.html
│   │
│   └── app/                 # ← the real frontend, new
│       ├── package.json
│       ├── next.config.ts
│       ├── src/
│       │   ├── app/                    # Next.js routes
│       │   │   ├── page.tsx             # search/home
│       │   │   ├── stock/[ticker]/[date]/page.tsx
│       │   │   └── api/…               (only if a BFF proxy is needed)
│       │   ├── components/
│       │   ├── lib/
│       │   │   ├── api-client/          # generated from api/openapi.json
│       │   │   └── poll.ts              # GET /runs/{id} polling logic
│       │   └── types/
│       └── public/
```

Why `design/` and `app/` as siblings rather than the app living directly in
`web/`:

- **The static comps have zero build step and should stay that way.** They're
  a reference to copy patterns from (see "What already exists" above), not
  code to compile. Keeping them out of the Next.js app directory means
  `next.config.ts`, `.next/`, `node_modules/` never sit next to them or risk
  confusion about which files are "the app."
- **One `package.json`, not a monorepo tool.** There's a single frontend
  package here — no shared UI library, no second app. Turborepo/Nx would
  solve a problem this repo doesn't have yet.
- **`lib/api-client/` is a generated-file boundary, made structural.** This
  doc already says to generate a typed client from `api/openapi.json` rather
  than hand-write types (see "The API contract" above) — giving it its own
  folder keeps generated code visibly separate from hand-written code.

The four paths (`web/DESIGN.md`, `web/landing-fintech/`, `web/landing/`,
`web/research/`) have been moved into `web/design/` — this move is already
complete.

## Suggested first screens (functional shape, not visual)

1. **Search / home** — ticker input, resolution feedback, recent runs
   (`GET /runs`)
2. **Stock / results page** — verdict, bull vs bear, analyst reports, raw
   data. Evidence above verdict.
3. **In-progress** — live stage polling, honest time estimate, failure
   state
4. **History** — repeat runs, `verdict_is_contested`

## Before calling anything done

- [ ] Both processes running; confirm a queued run actually transitions to
      `running` → `completed` (not stuck — means the worker is live)
- [ ] `POST /analyze` tested for both 202 (new) and 200 (cached) — UI
      branches correctly on each
- [ ] A 429 simulated (or read from `api/ratelimit.py` defaults) — cached
      reads still work while blocked from new runs
- [ ] A null `entry_price`/`stop_loss` renders as "Not set," never `0`
- [ ] A `failed` run renders its `error`, doesn't spin
- [ ] Long reports (sentiment, ~3,000 words) don't dump into one unbroken
      scroll
