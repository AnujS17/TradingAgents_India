# UI Handoff

Written 2026-08-12 for a fresh Claude Code session building the frontend. The
backend is finished and running; another session owns it. Read this before
writing code.

## What you are building

A web frontend for a multi-agent equity-research tool covering Indian markets
(NSE/BSE). A retail user types a ticker, requests an analysis, waits, and reads
what four analysts, a bull/bear debate, a trader and a risk panel concluded.

**Frame it as research, not advice.** Lead with evidence — the bull case, the
bear case, the numbers, the sources — rather than a giant BUY/SELL badge.
That is both the better product and a materially safer position under SEBI's
rules for a public tool in India. The API deliberately returns full reports,
not just a rating.

## Boundaries

- **Do not edit `tradingagents/`, `api/`, or `cli/`.** Another session owns the
  backend. If you need an API change, ask for it rather than making it.
- Build the frontend in its own directory (`web/` at repo root is fine).
- **Never add `Co-Authored-By: Claude` or any AI attribution** to commits or
  PR bodies. This is a standing rule for this repo.

## Running the backend locally

Two processes, both from the repo root:

```bash
# terminal 1 — the API
"E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe" -m uvicorn api.main:app --reload

# terminal 2 — the worker that actually runs analyses
"E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe" -m api.worker
```

API at `http://127.0.0.1:8000`, interactive docs at `/docs`.

**Without the worker running, nothing executes** — requests sit at `queued`
forever. That is expected, not a bug.

CORS already allows `http://localhost:3000`. Other origins need
`TRADINGAGENTS_API_ALLOWED_ORIGINS` set.

## The contract

`api/openapi.json` is the generated spec — import it to produce a typed client
rather than hand-writing types.

| Method | Path | Purpose |
|---|---|---|
| POST | `/analyze` | queue an analysis, or get the existing one |
| GET | `/runs/{id}` | poll one run |
| GET | `/runs/{ticker}/{date}` | what a stock page asks for |
| GET | `/runs/{ticker}/{date}/history` | compare repeat runs |
| GET | `/runs` | list, filter by ticker |
| GET | `/health` | dependency status |

### POST /analyze

```json
{ "ticker": "SIEMENS.NS", "analysis_date": "2026-08-12",
  "profile": "fast", "force": false, "refresh_data": false }
```

Only `ticker` is required. `analysis_date` defaults to today.

**The status code carries meaning:**
- **202** — a new run was queued. It will take minutes.
- **200** — an existing run was returned. Instant, free.

Treat both as success. 202 means the user spent an analysis.

- `profile`: `fast` (~4 min) or `detailed` (~14 min).
- `force`: run fresh even though one exists. The old run is KEPT, not replaced.
- `refresh_data`: also re-fetch news/filings rather than replaying the day's
  snapshot. Implies `force`.

**429** means a spend limit was hit. The body explains which. Cached reads are
never blocked, so a rate-limited user can still read existing analyses — say
that in the error UI rather than showing a dead end.

### Run shape

`status` is `queued` | `running` | `completed` | `failed`.
`verdict` and `reports` are **null until `completed`**.

`verdict` — every field is nullable, and null is normal:
`rating` (Buy/Overweight/Hold/Underweight/Sell), `price_target`,
`time_horizon`, and `levels` = `{action, entry_price, stop_loss,
position_sizing}`.

**Do not render a missing level as 0 or "—0".** A Hold that says "wait for a
pullback" legitimately has no entry price, and the engine deliberately drops a
stop-loss it cannot make coherent rather than emitting a misleading number. In
a real observed run, `price_target`, `entry_price` and `stop_loss` were all
null while `rating` and `action` were populated. That is correct behaviour.

`reports` — ten optional markdown strings: `market`, `sentiment`, `news`,
`fundamentals`, `bull_case`, `bear_case`, `investment_plan`, `trader_plan`,
`risk_debate`, `final_decision`. A real run totalled **11,375 words**, with
`sentiment` the largest at ~3,000. Plan for long content: collapsible sections,
a table of contents, or tabs. Do not dump it all into one scroll.

The markdown includes tables and rupee amounts (₹). Use a markdown renderer.

## The three UX problems that actually matter

**1. The wait is 4-14 minutes.** This is the hardest design problem in the
product. A blank spinner will read as broken. Poll `GET /runs/{id}` every few
seconds and show real progress — which stage is running. The response gives
`estimated_seconds` as a rough guide (not a promise). Consider letting the user
leave and come back; the run id is a durable link.

**2. Repeat runs can disagree, and the API tells you.** `verdict_is_contested`
is true when repeat analyses of the *same* question reached different ratings.
The day's data is snapshotted, so both runs read identical inputs — a split
means the evidence is genuinely balanced, not that something broke.

Surface it: *"Analysed 3 times — 2 said Underweight, 1 said Hold."* That is
useful information about conviction. Hiding it and showing whichever ran last
would be the dishonest option. `run_count` and the `/history` endpoint back
this view.

**3. Failure is a real state.** A run can end `failed` with an `error` string.
Show it plainly rather than spinning forever.

## Suggested first screens

1. **Search / home** — ticker input, recent runs
2. **Stock page** — verdict summary, then bull vs bear side by side, then the
   analyst reports, then the raw data. Evidence above verdict.
3. **In-progress** — live stage indicator, honest time estimate
4. **History** — repeat runs and whether they agreed

## Stack

Not decided — your call. Next.js is the obvious default; the API is plain REST
with an OpenAPI spec, so anything works. `frontend-design` and `typescript-lsp`
plugins are available and worth installing.

## Context you will not otherwise have

- A run costs real LLM money, so **do not hammer `force: true`** while
  developing. Re-request the same ticker and date without `force` — it returns
  the cached run instantly and free.
- Tickers are normalised server-side: `reliance` and `RELIANCE.NS ` hit the
  same cache entry. You do not need to normalise client-side.
- The backend stores runs in SQLite at `~/.tradingagents/api.db`. Deleting that
  file resets everything if you want a clean slate.
- Verdict ratings come from a 5-tier scale; `levels.action` is a separate
  3-tier field (Buy/Hold/Sell). They can differ legitimately — a `Hold` action
  under an `Underweight` rating means "trim, don't exit".
