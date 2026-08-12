# Performance Work — Handoff

Written 2026-08-11. Read this fully before touching anything. The goal of this
branch is making a single analysis run fast enough for an interactive web
platform (was 10–12 min; target ~2–3 min) **without degrading analysis
quality**.

## Where you are

- **Worktree:** `E:\Research papers\TradingAgents1\TradingAgents_Ind-perf-worktree`
- **Branch:** `perf-optimization` (tracks `origin/main`)
- **Main repo (do NOT edit):** `E:\Research papers\TradingAgents1\TradingAgents_Ind`
- **There is a second worktree** for UI work at `...-ui-worktree` on branch
  `ui-changes`, driven by a different Claude instance. Stay out of it.
- **Nothing on this branch is committed yet.** All work is uncommitted in the
  working tree.

### Running things

This worktree has **no `.venv` of its own** (gitignored), so use the main repo's:

```bash
cd "E:\Research papers\TradingAgents1\TradingAgents_Ind-perf-worktree"
"E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe" -m pytest tests/ -q
"E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe" -m cli.main analyze --fast
```

graphify (code navigation, per the project CLAUDE.md) uses a **different**
interpreter and has its own graph in this worktree:

```bash
"C:\Users\anujs\AppData\Local\Programs\Python\Python310\python.exe" -m graphify query "<question>"
```

### Test baseline — memorise this

**Currently 542 passed, 4 failed.** (Was 536/6 when this doc was first
written; +6 tests added since, and the 2 ollama failures below stopped
reproducing.) The failures are PRE-EXISTING and unrelated to any of this work.
Do not try to fix them, and do not treat them as your regression:

- 4 × `tests/test_adx_dmi_indicators.py` — ADX/DMI indicators are simply not
  implemented in `alpha_vantage_indicator.py`. Long-standing known gap.
- 2 × `tests/test_ollama_base_url.py` — Rich-console ANSI escape codes break
  substring assertions. Cosmetic, untouched by this work.

Anything beyond those 6 is yours.

---

## The core finding (this drives everything)

**Wall-clock time is dominated by output-token GENERATION**, not input size,
not network. Measured on a real default run (SIEMENS.NS):

| Report | LLM-written words |
|---|---|
| fundamentals | ~2,560 |
| news | ~2,470 |
| market | ~2,094 |
| sentiment | ~1,286 |

That is ~8,400 words (~11k tokens) from the analysts **alone**, before the 8
debate/manager calls. At DeepSeek's ~30–50 tok/s that is most of a 10-minute
run.

**Corollary:** prompt wording ("be concise") is a request a model may ignore.
Only two things reliably shorten output: an explicit **numeric** limit in the
prompt/schema, and a hard `max_tokens` cap enforced by the API.

---

## What is implemented (all done, all tested)

### 1. `get_fast_config()` — `tradingagents/default_config.py`

Opt-in profile. Deep-copies `DEFAULT_CONFIG` (never mutates it). Sets:

| Key | Default → Fast | Why |
|---|---|---|
| `max_debate_rounds` / `max_risk_discuss_rounds` | 2 → 1 | Cuts 10 sequential LLM calls to 5. Still a full Bull→Bear exchange and a full 3-way risk pass — only the second iteration is cut. |
| `report_style` | detailed → concise | Selects short prompts + concise schema variants. |
| `max_output_tokens` | None → 1400 | Hard API cap. |
| `analyst_concurrency_limit` | 1 → 4 | Runs the 4 analysts in parallel. |
| `news/global/india article limits` | lowered ~40–60% | Smaller prompts. |
| `reddit_subreddits` | None (all 7) → top 3 | Reddit's worst case scales with subreddit count. |
| `data_vendors` / `tool_vendors` | gdelt removed | GDELT was fallback-only and adds ~45s when throttled. |

**Deliberately NOT touched:** `company_news_lookback_days` (30). Narrowing it
would reintroduce a real "no news found" bug for sparsely-covered Indian
mid-caps. Only per-fetch article COUNT is trimmed, never the window.

### 2. `--fast` CLI flag — `cli/main.py`

`analyze(--fast)` → `run_analysis(fast=True)` → uses `get_fast_config()`.

**The subtle part:** `run_analysis()` unconditionally overwrites
`max_debate_rounds` from the interactive "Research Depth" prompt
(Shallow=1/Medium=3/Deep=5) *after* config is built. So `--fast` **skips that
prompt entirely** and pins it to 1. Without that, picking "Deep" would clobber
the trim to *worse than default*. Guarded by
`tests/test_cli_fast_flag.py`, including a test that raises if
`select_research_depth()` is called at all in fast mode.

### 3. Output token cap — universal

`max_output_tokens` → `_get_provider_kwargs()` maps to the right per-provider
name (`max_output_tokens` for Google, `max_tokens` for Anthropic + all
OpenAI-compatible incl. DeepSeek). **openrouter excluded** — it already has
`openrouter_max_completion_tokens`.

Before this, **no provider except openrouter had any cap at all**. Required
adding `max_tokens` to `_PASSTHROUGH_KWARGS` in `openai_client.py` or it was
silently dropped. Verified end-to-end that it lands on the real model object.

**1400 is a deliberate safety CEILING, ~3x what prompts ask for — not the
primary lever.** A tight cap would truncate structured JSON mid-object → parse
failure → fallback triggers a SECOND full call → *slower*. Prompts do the work.

### 4. Prompt trimming — explicit numeric limits

| Agent | Concise target |
|---|---|
| market / fundamentals | 250 words each |
| news | 300 words, ≤8 coverage bullets |
| bull / bear | 200 words |
| 3 risk debators | 180 words |

Markdown tables dropped in concise mode (token-expensive scaffolding).
Shared helper: `get_brevity_instruction(max_words)` in `agent_utils.py`
(returns `""` when detailed, so default is byte-identical).

**Evidence/citation guardrails are unconditional in BOTH modes** — asserted by
parametrized tests. Trimming verbosity must never trim accuracy discipline.

### 5. Concise schema variants — `schemas.py`

**Critical gotcha:** for the 4 structured-output agents (Sentiment, Research
Manager, Trader, Portfolio Manager), langchain sends the **pydantic JSON
schema** to the provider — the **field descriptions ARE the output
instructions**. An earlier pass trimmed only the prompts and these agents did
not shrink at all, because the sentiment schema still said *"Full sentiment
report covering, in order: (1)…(5) a markdown table."*

`concise_variant(model, overrides)` rebuilds the model with short
descriptions. It **deepcopies FieldInfo before mutating** — `create_model(__base__=...)`
leaves the subclass sharing FieldInfo objects with the parent, so an in-place
edit would rewrite the ORIGINAL schema and silently make the detailed path
concise too. Tested.

Honest note: `TraderProposal.reasoning` and `PortfolioDecision.executive_summary`
**already** said "two to four sentences" — those two overrides are marginal.
The real wins are `SentimentReport.narrative` and the previously-uncapped
`ResearchPlan.rationale` / `strategic_actions` / `investment_thesis`.

### 6. Parallel analysts — the big structural change

`analyst_concurrency_limit` was threaded from config all the way into
`AnalystExecutionPlan` and **then never read** by `setup.py`, which always
built a strict chain. Reading it alone would have produced a broken graph:

- **Shared `messages` channel.** All 4 analysts wrote one channel, and every
  ReAct routing decision reads `messages[-1]`. Under parallelism the merge
  order is nondeterministic, so `should_continue_news` could read the MARKET
  analyst's tool-call message and route the news branch into `tools_news`.
  **Fix:** per-analyst channels (`market_messages`, `sentiment_messages`,
  `news_messages`, `fundamentals_messages`) in `AgentState`, plumbed through
  `AnalystNodeSpec.messages_key`, `ToolNode(messages_key=...)`,
  `create_msg_delete(messages_key)`, `conditional_logic`, and
  `propagation.create_initial_state` (all 4 must be seeded).
- **`audit_tool_calls` had no reducer.** Its `Annotated[...]` second arg was a
  *docstring*; LangGraph only treats it as a reducer if **callable**. Now
  `operator.add`, or concurrent appends raise `InvalidUpdateError`.
- **`_dedupe_tool_call`** read only the shared channel — would have silently
  become a no-op. Now searches all channels.

**Fan-in — read this before changing the wiring.** I got this wrong once and
it reached production. N individual `add_edge(clear_node, "Bull Researcher")`
calls are **NOT a barrier** — each analyst independently *triggers* the
debate. Market/fundamentals run extra ReAct rounds, finish in later
supersteps, and re-trigger `Bull Researcher` while the bull/bear loop is
already running → two nodes write `investment_debate_state` in one step →
`InvalidUpdateError: Can receive only one value per step`.

The correct form is ONE multi-source edge:
```python
workflow.add_edge([spec.clear_node for spec in plan.specs], "Bull Researcher")
```

My first test suite **missed this** because every stub analyst finished in the
same superstep. `test_staggered_analyst_completion_does_not_double_trigger_the_debate`
gives each analyst a different round count (3/2/1/1) and was verified to fail
("debate node ran 3 times") when the fix is reverted.

---

## New test files (all written this session)

| File | Covers |
|---|---|
| `test_fast_config.py` | profile values, no mutation of DEFAULT_CONFIG, nested-dict siblings preserved |
| `test_cli_fast_flag.py` | `--fast` wiring, research-depth prompt skipped |
| `test_output_token_cap.py` | per-provider kwarg mapping, cap reaches real model object |
| `test_concise_schemas.py` | schema variants, no parent mutation, constraints preserved |
| `test_report_style.py` | detailed vs concise prompts, guardrails in both |
| `test_parallel_analysts.py` | concurrency probe, channel isolation, staggered fan-in |

---

## MEASURED END-TO-END — target met

Measured from the logs of the real HDFCBANK.NS run at 19:59 on 2026-08-11
(`C:\Users\anujs\.tradingagents\logs\HDFCBANK.NS\2026-08-11\`). No new run was
needed — `message_tool.log` is timestamped and ends with a completion line.

**19:59:42 start → 20:01:35 complete = 113s (~1m53s).** Was 10–12 min. Target
of 2–3 min is met.

Phase split:

| Phase | Window | Duration |
|---|---|---|
| Pre-fetch I/O (all tools) | 19:59:43 → 20:00:16 | ~33s |
| Analysts + research debate + trader | 20:00:16 → 20:01:03 | ~47s |
| Risk debate + portfolio manager | 20:01:03 → 20:01:35 | ~32s |

**The prompts and schemas ARE being obeyed.** LLM-written words per report,
counted from the section after the `## … Analyst Report` marker (everything
before it is the pre-fetched raw data block, which is NOT LLM output — do not
`wc -w` the whole file, it triples the number):

| Report | Target | Fast run | Old default run (SIEMENS) |
|---|---|---|---|
| market | 250 | 255 | 2,049 |
| news | 300 | 325 | 2,425 |
| sentiment | — | 138 | 1,258 |
| fundamentals | 250 | 207 | 2,516 |

~925 words vs ~8,250. LLM generation is no longer the dominant cost.

### Wall-time instrumentation was lying — fixed

That run printed `Market 34.22s | Sentiment 0.00s | News 0.00s |
Fundamentals 11.20s`. The two zeros were a measurement bug, not fast analysts.

`sync_analyst_tracker_from_chunk` encoded the sequential assumption that
exactly one analyst is active at a time: it marked only the *first* spec
without a report as started. Under parallel fan-out all four run at once and
several reports first appear in the SAME chunk, so those analysts were marked
started and completed at the same instant → 0.00s. Fundamentals' 11.20s was
wrong the same way (it had really been running since t=0).

Fix: `AnalystWallTimeTracker.mark_launched()` starts every analyst when
`concurrency_limit > 1` (only the first when sequential), and the chunk sync
takes the same parallel branch. `cli/main.py` calls `mark_launched()` instead
of marking just `selected_analyst_keys[0]`.

Guarded by 4 new tests in `tests/test_analyst_execution.py`, including
`test_parallel_analysts_finishing_together_do_not_report_zero`, which
reproduces the exact observed output and **was verified to fail when the fix
is reverted**. `test_sequential_sync_still_serialises_starts` pins the
sequential path so the parallel branch cannot leak into it.

Suite now **542 passed, 4 failed** — the 4 are the ADX/DMI baseline. (The 2
`test_ollama_base_url.py` failures listed below no longer reproduce here.)

---

## Quality investigation (2026-08-12) — verdict flips are NOT caused by `--fast`

Prompted by two `--fast` runs (LICI.NS, HDFCBANK.NS) appearing to return the
opposite verdict from earlier runs.

### LICI.NS has three runs in one log — read them before theorising

| # | Window | Mode | Verdict |
|---|---|---|---|
| 1 | 12:58:21 → 13:10:54 (753s) | default | **HOLD** |
| 2 | 13:15:16 → 13:27:56 (760s) | default | **BUY** |
| 3 | 22:39:44 → 22:41:55 (131s) | **fast** | **BUY** |

**Runs 1 and 2 were both DEFAULT mode, 12 minutes apart, same ticker, same
date, same fetched data — and disagreed with each other.** The fast run agrees
with default run 2. The flip predates `--fast` entirely.

**Root cause: nothing pins sampling.** `temperature` and `top_p` are set only
for openrouter (`default_config.py:61-62` → `trading_graph.py:254-259`). Every
other provider gets no temperature and no seed, so provider-default sampling
(~1.0) applies and two identical runs can diverge. Note that pinning
temperature would *reduce* variance, not eliminate it — most providers do not
guarantee reproducibility even at 0.

**HDFCBANK.NS cannot be checked.** Its log holds only one completed run
(19:59, fast, BUY); the 19:27 attempt has no completion line. There is no
baseline on disk to compare against.

### Report quality did NOT degrade in fast mode

The fast run's fundamentals figures match run 2's fully-fetched detailed
report exactly: FY26 net income ₹574.5bn / +18.9%, revenue ₹9.69tn / +8.7%,
BVPS ₹139.6, total assets ₹59.5tn, investment book ₹54.9tn, 6.9x forward,
FCF −₹273bn (= run 1's "₹27,300 crore"). Concise mode compressed the
presentation, not the evidence.

If anything run 1 — the *slow, detailed* one — was the weaker analysis: it
made negative FY26 FCF a bear pillar ("the bear case wins on earnings
quality"), while runs 2 and 3 correctly identified it as an insurance
accounting artifact (policy payouts sit in operating cash flow). The 1-round
fast debate still engaged and rebutted the bear case explicitly in
`investment_plan.md`.

### The log was lying — fixed

`cli/main.py` read only `chunk["messages"]`. The analysts no longer write
there: each owns its own channel, and **that split is unconditional in
`setup.py`, not gated on parallel mode**. So every analyst ReAct tool call and
agent message silently vanished from `message_tool.log` and the live display
in BOTH modes, starting with the first post-parallelisation run.

This is what made the LICI fast run look like it never called
`get_fundamentals` / `get_balance_sheet` and had invented its numbers. It had
not — only the pre-fetch calls were visible, because those arrive separately
via `audit_tool_calls`.

Fix: `get_message_stream_channels(plan)` returns `messages` plus every
per-analyst channel; the CLI iterates all of them (dedup by message id already
handles any overlap). Guarded by `MessageStreamChannelTests`, including a test
that every key in `ANALYST_NODE_SPECS` is reachable so a future analyst cannot
go silently unlogged the same way.

**Lesson, same shape as the two in the section at the bottom of this file:**
the observability layer was not updated alongside the state-channel split, so
for one session the logs described a pipeline that no longer existed. Check
that instrumentation still reads the channels the graph actually writes.

Suite after these fixes: **546 passed, 4 failed** (ADX/DMI baseline).

---

## Quality comparison vs full detailed runs (2026-08-12)

Two fresh **detailed** runs from the MAIN repo (pre-perf code), compared
against the 08-11 fast runs.

| Ticker | Fast (08-11) | Detailed (08-12) | Verdict |
|---|---|---|---|
| HDFCBANK.NS | 113s, **BUY** | 871s (14.5m), **HOLD** | **flipped** |
| LICI.NS | 131s, **BUY** | 740s (12.3m), **BUY / Overweight** | same |

LLM words, HDFCBANK (analyst reports, prefetch blocks excluded): fast 925
(255/325/138/207) vs detailed 7,736 (2,400/1,413/1,506/2,417). Debate + risk +
portfolio: fast 342 vs detailed 10,550. ~14x overall.

### Three real quality gaps in concise mode — all in `fundamentals`

These are content differences, not sampling noise. All three are visible by
diffing HDFCBANK's fast `fundamentals_report.md` against the detailed
`1_analysts/fundamentals.md`.

1. **Vendor data-quality caveats are gone.** The detailed report flags that
   `Common Stock Equity` (₹8.17 lakh crore) and vendor ROE (13.84%) "are not
   mutually reconcilable with a simple NI/avg-equity calc (~9–10%) — treat
   vendor aggregates as directional", plus EPS/share-count mismatches in
   Q3/Q4 FY2025. **The fast report states ₹8.17tn equity and 13.8% ROE as
   fact.** ROE 13.8% vs ~9–10% materially changes the investment case.
2. **Forward estimates are not interrogated.** Both runs derive the same
   figures (11.65x forward, PEG 0.89, forward EPS ₹62.60, ~37% implied
   growth). The detailed run tests them — "if NIM stays suppressed and credit
   costs rise, the cheapness is a value trap", and separately surfaces FY26
   net-profit growth of **+4.6%** as evidence against forward-consensus
   credibility. The fast report states the 37% and stops; +4.6% never appears.
   That single unexamined number is the pivot of the whole HOLD case.
3. **A statement fetch is missing.** Fast: "No cash-flow statement data
   available; funding quality is inferred". Detailed: annual cash flow
   retrieved fine (OCF ₹1,118.6bn FY26), only *quarterly* unavailable — it
   called `get_cashflow` twice, once per freq. Strong inference: under the
   concise prompt the model made one pass, got the empty quarterly result and
   did not retry annual. Not confirmable from the fast log (see the
   observability bug above), so treat as inference, not fact.

**Why LICI did not flip.** Its bull case rests on *realized* Q1 results (PAT
+24%, VNB +61.3%, margin 15.4%→22.9%) and its data was clean — the detailed
report raises no reconciliation caveats. There was nothing for the extra depth
to interrogate. HDFCBANK's bull case rested entirely on a forward estimate,
which is exactly what concise mode stops examining.

**Working hypothesis: concise mode degrades in proportion to how much the
thesis depends on estimated rather than realized inputs.** Worth testing on
more tickers before treating as settled.

### Confounds — do not attribute the flip to concise mode alone

Three causes are entangled and this evidence cannot fully separate them:

1. Concise mode dropping the caveats and the forward-estimate test (shown
   above).
2. **One extra day of materially more bearish news.** 08-12 added "HDFC's
   triple-hit valuation looks hard to restore", "Rushing To Tap Dollar
   Funding", and "Jefferies' India portfolio bet: why MCX, Lenskart and Bajaj
   Finance made the cut over HDFC Bank". That supports HOLD on its own.
3. **Sampling variance**, already proven capable of flipping a verdict by the
   two default LICI runs on 08-11.

A clean test needs fast vs detailed on the **same analysis date**, repeated
2–3x per arm to separate signal from sampling.

---

## Data-completeness fix (2026-08-12) — fast mode no longer fetches less

Acting on the SIEMENS.NS result. **New invariant, asserted by tests:**

> Fast mode changes how much the model WRITES and how work is SCHEDULED.
> It never changes how much data the model SEES.

### 1. Fundamentals analyst: ReAct → pre-fetch (the actual bug)

The statement tools default to `freq="quarterly"`. As a ReAct agent this
analyst never passed the argument, so it fetched quarterly only and **never
retrieved an annual statement** — losing every multi-year trend, and producing
HDFCBANK's "No cash-flow statement data available" (that vendor has no
quarterly cash flow; annual was fine).

It now pre-fetches all 8 blocks — bulk deals, the overview, and income
statement / balance sheet / cash flow in **both** frequencies — **concurrently**
via `ThreadPoolExecutor`, and no longer binds tools at all. The data no longer
depends on the model choosing to ask for it. A failed block degrades to
`<name(freq) unavailable: ...>` inline so the model can caveat it rather than
silently reason without it.

Dropping the ReAct loop also removes its round-trips; this was the slowest
analyst on the fast profile (54.38s on SIEMENS).

**New state channel `fundamentals_synthesis`**, mirroring `news_synthesis` and
for the same reason: `fundamentals_report` now carries six statement blocks
(kept for the human record and hallucination audits), which must not be
re-embedded into all 5 debate/risk prompts every round. Those 5 nodes read the
synthesis. `test_debate_static_dynamic_split` guards the leak both ways.

### 2. Two prompt obligations are now unconditional

Alongside the existing evidence/citation guardrails, in BOTH styles:

- use ANNUAL blocks for trend claims and QUARTERLY for the latest print —
  *"a single quarter is not a trend"*;
- state what a forward multiple assumes, and if two vendor figures cannot be
  reconciled, say so and prefer the one derivable from the statements.

These target the exact HDFCBANK failures (vendor ROE 13.84% vs a derivable
~9–10%; PEG 0.89 quoted without naming its 37%-growth assumption).

### 3. Input trims reverted from `get_fast_config`

Removed: article caps (news 30→12, global 20→10, india 8→4, global-india
10→5), `reddit_subreddits` 7→3, and the gdelt removal from both vendor chains.
Input size is not what costs wall-clock — output generation is — so these
bought little speed while making the two modes incomparable on quality. gdelt
mattered most: fallback-only, so its absence is invisible until a primary
vendor fails and fast mode silently has no fallback.

`get_fast_config` now changes exactly five keys, pinned by a whitelist test so
an input-reducing key cannot be added silently:
`max_debate_rounds`, `max_risk_discuss_rounds`, `report_style`,
`max_output_tokens`, `analyst_concurrency_limit`.

### Deliberately NOT changed

`get_stock_data` (market analyst) is optional **by design** — the prompt names
the pre-fetched snapshot as the source of truth and says to call it "only if
you need raw daily OHLCV beyond the snapshot's own recent-closes table". The
fast run not calling it is intended behaviour, not the freq bug. Force-fetching
a year of daily OHLCV into every market prompt would contradict that design.

Suite: **547 passed, 4 failed** (ADX/DMI baseline). Both parallel and
sequential graphs verified to compile. The freq regression test was verified
to fail when `_STATEMENT_FREQUENCIES` is reverted to quarterly-only.

---

## Trader entry/stop bug (2026-08-12) — schema descriptions, not concise mode

**It is a prompting bug, but not where I first guessed.** `trader.py` says
nothing whatsoever about entry, stop or levels, and `CONCISE_TRADER_OVERRIDES`
only touches `reasoning`. So the two `Field(description=...)` strings were the
model's *only* instruction — another instance of §5's finding that for
structured agents the field descriptions ARE the prompt.

The old wording — "Optional entry price target in the instrument's quote
currency" / "Optional stop-loss price ..." — stated no relationship between
the two fields and never said when omitting was correct. Three malformed pairs
resulted, **spanning both report styles**, which is what rules out concise
mode as the cause:

| Run | Action | Entry | Stop | Defect |
|---|---|---|---|---|
| SIEMENS fast 2026-08-12 | Hold | 3700.0 | 3700.0 | identical |
| SIEMENS **detailed** 2026-08-11 | Hold | 3650.0 | 3736.0 | stop above entry |
| SIEMENS fast (pre-fix) | Sell | 3900.0 | 3650.0 | stop below entry on a short |

All three are Holds or near-Holds — exactly where "entry price" has no natural
answer, so the model back-filled a number from the prose. "Optional" was not
enough; the description has to say when `null` is the RIGHT answer.

**Fix, two layers:**

1. Descriptions now state the relationship (stop strictly below entry for Buy,
   strictly above for Sell, never equal) and name the omit case explicitly
   ("a Hold that says 'wait for a pullback' should leave this null rather than
   quote the level you are waiting for. Never invent a number").
2. `TraderProposal._drop_incoherent_levels`, a `model_validator(mode="after")`
   that **normalises rather than raises** — a ValidationError would fail the
   structured parse, trigger the fallback and cost a second full LLM call (the
   trap in §3). Only the stop is dropped, since between the two it is the one
   whose validity is checkable.

Emitting "Stop Loss: 3700.0" under "Entry Price: 3700.0" is worse than
emitting nothing: a reader can size a position against protection that does
not exist.

**CORRECTION — the first version of this rule was wrong.** It required
`stop > entry` for Sell, on the assumption that Sell opens a short. **This book
is long-only**: there is no shorting anywhere in the codebase (grep for
short/shorting returns nothing), `PortfolioRating` runs Buy..Underweight/Sell,
and every observed Sell says trim, e.g. "Reduce SIEMENS.NS into strength near
₹4,000 ... stop below ₹3,800". Sell reduces a long, so the stop guards the
*retained* long and belongs BELOW entry — same as Buy and Hold.

That first rule would have discarded the **correct** pair entry 3900.0 /
stop 3650.0 as malformed. So there were only ever **two** genuine defects, not
three:

| Run | Action | Entry | Stop | Verdict |
|---|---|---|---|---|
| SIEMENS fast 2026-08-12 | Hold | 3700.0 | 3700.0 | broken (identical) |
| SIEMENS **detailed** 2026-08-11 | Hold | 3650.0 | 3736.0 | broken (stop above) |
| SIEMENS fast 2026-08-12 | Sell | 3900.0 | 3650.0 | **correct** — trims a long |

The rule is now simply `stop < entry` for all three actions.

Verified against all six real observed pairs through both the base model and
`concise_variant` (the validator is inherited, so it survives the
`create_model(__base__=...)` rebuild — checked explicitly, since §5 documents
that variant construction has surprised us before).

Suite: **556 passed, 4 failed** (ADX/DMI baseline).

---

## "Tools: 0" in the CLI (2026-08-12) — a regression from the pre-fetch work

`StatsCallbackHandler.on_tool_start` is a **LangChain callback**: it fires only
when LangChain invokes a tool, i.e. from a ReAct ToolNode. Analysts pre-fetch
by calling `tool.func(...)` directly, which bypasses LangChain entirely.

Market, news and sentiment already pre-fetched, so **fundamentals was the last
analyst making real ReAct calls**. Moving it to pre-fetch dropped the counter
to zero — the header read "Tools: 0" on a run that made **17** data fetches.
The display was reporting the mechanism, not the work. `message_tool.log` was
correct throughout (17 `[Tool Call]` / 17 `[Data]` lines).

Fixed by `StatsCallbackHandler.record_prefetch()`, called from the CLI's
`audit_tool_calls` loop — already deduplicated by `MessageBuffer.add_tool_call`,
so each distinct fetch counts once.

**Generalise the lesson:** this is the third time instrumentation has been left
behind by a structural change (wall-time tracker, message channels, now the
tool counter). When work moves off a framework path, check what was counting it.

---

## Demerger trap got WORSE — it is now an active error

Run `SIEMENS.NS_20260812_111104`. Previously the fast run merely *omitted* the
demerger catch. It now commits the error, as **Bullish Point #3** in the news
analyst's output:

> "Sister co Siemens Energy India Q1 profit +70% **signals group demand
> strength**."

and in sentiment: "peer posts (Hitachi Energy, GE Vernova) **reinforcing the
grid-expansion theme**".

This is exactly the read-through the detailed baseline's bear ruled invalid —
that segment demerged on 07-Apr-2025 and does not accrue to SIEMENS.NS. It now
feeds downstream as a *bullish argument*. It did not change this run's verdict
(Sell/Underweight), so it is latent, not yet material.

Note it correctly calls it "Sister co" — it knows the entity is separate, and
still draws a bullish inference for SIEMENS.NS from its results. Restoring the
article limits (30 → 41 articles) put more Siemens Energy content in the feed,
which plausibly raised the salience.

**This is not fixable by pre-fetching more data.** The fact is present and
correctly labelled; what is missing is the inference step. The candidate fix is
a guardrail in the news/sentiment prompts, in both styles: results from a
separately-listed entity are not read-through, name the demerger when citing
one. Not implemented — it needs a decision on whether to hard-code
corporate-action awareness or derive it from the NSE filings block.

---

## Depth restored to fast mode (2026-08-12) — output length WAS the mechanism

Resolves an apparent contradiction in the notes above: fast mode was said to
change "output length and scheduling only", yet also to lose reasoning depth.
Both are true, because **for an LLM output length IS reasoning depth** — the
model reasons in the tokens it writes.

Proven on SIEMENS.NS 2026-08-12, fast 11:00 vs detailed 11:16. Both ran
**exactly one debate round and one risk round** (verified by counting turns in
every artifact), identical data, 16 minutes apart. So the word caps were the
only variable, and the mechanism is visible in the template:

- concise: `8 bullets MAXIMUM, one line each` + `No markdown table`
- detailed: `one bullet per material item` + table

The fast Coverage section hit exactly 8 bullets. The 07-Apr-2025 Demerger
filing lost its slot to a fresher headline while "Siemens Energy gas-turbine
backlog ~70 GW" kept one. With the disqualifying fact gone, the fast run wrote
as a **bullish** point: "Sister co Siemens Energy India Q1 profit +70% signals
group demand strength." The detailed run had room for the demerger bullet and
the table (where it tagged rows "(separate entity)") and inverted the
inference: the ecosystem is booming "yet Siemens Limited's core profit is
falling".

**A cap does not merely compress the write-up; it forces a SELECTION, and
qualifying facts lose to newsworthy ones. One line is enough to assert a fact
but not to qualify it.**

`report_style = "concise"` and `max_output_tokens = 1400` are therefore removed
from `get_fast_config`. The user chose depth over latency explicitly.

**Fast mode now differs from default in three keys only:**

| Key | Default → Fast |
|---|---|
| `analyst_concurrency_limit` | 1 → 4 |
| `max_debate_rounds` | 2 → 1 |
| `max_risk_discuss_rounds` | 2 → 1 |

Only the first is free. The debate-round trim is a genuine depth reduction,
but it is **parity with every detailed run compared against so far** — those
were all run at Shallow (1 turn per agent, verified). Raise both to 2 if
beyond-parity depth is wanted.

Expected cost: the detailed analyst phase was 96+78+172+118 = 464s sequential;
parallel it is ~172s, so ~800s becomes roughly **~500s (8-9 min)** rather than
126s. Fast drops from ~6.4x to ~1.6x. **Unmeasured — that is arithmetic, not a
measurement.**

The per-provider `max_output_tokens` plumbing stays live for anyone who sets
the key deliberately; it is simply no longer part of `--fast`.

The concise prompt branches and `concise_variant` are all still in the code and
still tested — nothing was deleted, only unhooked from the fast profile.

---

## "balanced" report style (2026-08-12) — the middle setting

Full-depth fast was measured (`SIEMENS.NS_20260812_124147`, 609s) and the
entity hygiene came back: the news analyst produced a dedicated section header
"Siemens Energy India (related listed entity — context only, separate ticker)"
and a table row tagged "(related entity, separate ticker)". The miscrediting
error was gone. But at 609s vs 126s that is most of the speed given up.

**Measured output volume, LLM-written words, same ticker/date:**

| Profile | Analysts | Debate→portfolio | Total | vs detailed | Wall |
|---|---|---|---|---|---|
| concise (old fast) | 866 | 1,135 | 2,001 | **−88%** | 126s |
| full-depth fast | 7,781 | 8,808 | 16,589 | −4% | 609s |
| detailed | 7,896 | 9,423 | 17,319 | — | 801s |

So the old fast profile was writing **~1/8th** of a detailed run.

**`report_style` now has three values.** The new `"balanced"` is what `--fast`
selects, and it targets the two *structural* causes rather than just raising
word counts — those are what the demerger failure actually turned on:

| | detailed | balanced | concise |
|---|---|---|---|
| Length budget | none | 2.5x concise | 1x |
| Markdown tables | yes | **yes** | no |
| News coverage bullets | unlimited | **20** | 8 |
| Bull/bear points | unlimited | 6 each | 3 each |
| Analyst word cap | — | 625 | 250 |
| News word cap | — | 750 | 300 |
| Debate word cap | — | 500 | 200 |

Plus one rule now unconditional in **every** length-limited style:

> "Never drop an exchange filing that records a corporate action (demerger,
> spin-off, merger, scheme of arrangement) to save space — it is what makes
> every other figure comparable, and it is exactly the item that gets cut
> first because it is not news."

and under balanced the news table must carry a column "identifying WHICH
listed entity each item belongs to — this ticker, its parent, a demerged or
separately-listed affiliate, or an unrelated peer."

Implemented via `get_report_style` / `is_length_limited` /
`keeps_markdown_tables` / `scale_word_budget` in `agent_utils`, so the three
styles live in one place instead of a three-way branch in five files.
`"concise"` is retained and still tested; it is simply no longer what `--fast`
selects.

**Projected, NOT measured:** roughly 5,000-6,500 words (~30-38% of detailed,
i.e. a ~62-70% cut) and ~250-350s. Needs a run to confirm — in particular
whether 20 bullets is enough for the demerger filing to survive.

---

## Verdict stability (2026-08-12) — inputs frozen + sampling pinned

Verdicts flipped between identical runs (LICI.NS 08-11: two default runs 12
minutes apart gave HOLD then BUY; SIEMENS.NS 08-12: Hold and Sell/Underweight
across same-day runs). Investigation found **three** causes, not one.

### Cause 1 — the inputs were never the same (biggest, now fixed)

Measured: two SIEMENS.NS runs **11 minutes apart with the market closed**.
Verified market snapshot byte-identical; **22 of 63 news headlines differed**.
The Sensex line moved from "-325 points, Nifty below 24,400" to "-600 points,
Nifty below 24,300", and "Siemens Boosts Full-Year Guidance" appeared.

Price data was already disk-cached (hence the identical snapshot). Every
news/social/filings fetcher used only `lru_cache` — **in-memory, dies with the
process** — so each run started cold and re-pulled a rolling feed.

`dataflows/snapshot_cache.py` adds `snapshot_cached(namespace)`, stacked
*inside* the existing `lru_cache` on all six live fetchers (`google_news`,
`india_news`, `nse_filings`, `stocktwits`, `reddit`, `nse_bulk_deals`). Keyed
on (namespace, args, snapshot date), so a different analysis date still
re-fetches. `propagate()` sets the date; **the decorator is inert until then**,
so tests and ad-hoc dataflow calls are unchanged. `--refresh` bypasses it.

Two design notes worth keeping:
- The date is a **module global**, not a config key or contextvar. Config
  leaked between pytest cases and wrote real dirs into `~/.tradingagents/cache`;
  contextvars do not propagate into `ThreadPoolExecutor` workers, and the
  fundamentals pre-fetch uses exactly such a pool.
- Read/write failures are swallowed. A cache is an optimisation, never a
  correctness dependency — `test_an_unwritable_cache_never_breaks_the_fetch`.

### Cause 2 — nothing pinned sampling (now fixed)

`temperature`/`top_p` were set **only for openrouter**; every other provider
ran at its own default (~1.0) with no seed. Now `llm_temperature` (0.2) and
`llm_seed` (42) apply to every provider via `_get_provider_kwargs`.

`0.2` not `0.0` deliberately: the bull/bear and 3-way risk debates are
adversarial, and a fully greedy decode pushes the opposing agents toward
near-identical phrasing, weakening the disagreement the structure exists to
produce. Set to `0.0` for maximum determinism if you accept that trade.

`seed` had to be added to `_PASSTHROUGH_KWARGS` in `openai_client.py` or it was
silently dropped — the same trap `max_tokens` hit earlier. Anthropic and Google
expose no seed, so temperature is the only lever there.

**This narrows the spread; it does not eliminate it.** No major provider
guarantees bitwise reproducibility — batching and MoE routing shift results
regardless of seed. Do not promise determinism on the back of this.

### Cause 3 — genuinely borderline calls (NOT addressed)

Every observed flip is between **adjacent** ratings (Hold ↔ Underweight/Sell,
never Buy ↔ Sell). For SIEMENS the evidence really is balanced. If flips
survive frozen inputs and pinned sampling, this is what is left, and the
honest fixes are ensembling just the portfolio-manager call (it is one LLM
call) or reporting dispersion — "Underweight (4/5 runs)" — rather than
manufacturing false certainty.

Suite: **578 passed, 4 failed** (ADX/DMI baseline).

## NEXT STEP — this is where you pick up

**Re-run SIEMENS.NS `--fast` on the balanced profile and re-score it.** The
specific thing to check is whether the 07-Apr-2025 Demerger filing appears in
the news Coverage bullets and whether the entity column is populated. If it
does, balanced is the right default. If it does not, raise the bullet cap
again before reaching for full depth.

Also re-score against
`QUALITY_BASELINE_SIEMENS.md`. The previous score was 2 present / 2 weakened /
3 absent. Claims #2 (three-period deterioration) and #5 (FCF quality) should
now be reachable — the annual data they need is fetched. Claim #6 (caveats) is
targeted by the new unconditional obligations. Claim #1 (the demerger trap)
is untouched by this work and is the honest open question.

Watch the fundamentals wall time: 8 concurrent fetches replace ~4 serial ones
plus 2 LLM round-trips, so it should get *faster*, but that is a prediction,
not a measurement.

Then: verdict stability and concise-mode quality remain open.

0. **Run the controlled comparison**: same ticker, same analysis date, fast vs
   detailed, 2–3 repeats each. Nothing above separates the three confounds
   without it. **In progress — SIEMENS.NS.** The detailed baseline is
   characterised in `QUALITY_BASELINE_SIEMENS.md`, with a 7-claim scorecard
   pre-registered before seeing the fast arm. Two HDFCBANK confounds are
   absent there: same analysis date, and the baseline already ran 1 debate /
   1 risk round, matching what `--fast` pins.
0b. **Consider making the fundamentals prompt's data-quality and
   forward-estimate discipline unconditional**, the way the evidence/citation
   guardrails already are in both modes (see §4). The 250-word cap can stay;
   what should not be optional is "reconcile vendor aggregates" and "state what
   the forward estimate assumes". That is trimming accuracy discipline, which
   §4 explicitly says must never happen.

1. **Decide whether to pin sampling.** Setting `temperature` (and a `seed`
   where supported) for non-openrouter providers would cut run-to-run
   variance. It is not a pure win — it also removes the ensemble diversity the
   debate structure arguably relies on, and does not guarantee reproducibility.
   Not done; needs a product call.
2. **The deeper signal is robustness.** A BUY/HOLD that flips on resample means
   the bull and bear evidence was genuinely balanced for that ticker. Consider
   surfacing confidence/dispersion rather than only suppressing the variance.
3. Pre-fetch I/O remains the largest latency block (~33s of 113s) if you go
   back to speed.

### Known remaining levers, not yet done

- **Pre-fetch I/O is still serial inside each analyst.** e.g. `news_analyst`
  awaits get_news → get_global_news → india news → NSE filings → StockTwits
  one after another. Those are independent network calls and could run
  concurrently. This is likely the largest remaining win now that LLM output
  is capped.
- The **debate phase is still 5 sequential LLM calls** and cannot be
  parallelized (each turn responds to the previous). Only fewer rounds or
  shorter outputs help there.
- `analyst_concurrency_limit` is currently all-or-nothing (`>1` = full
  fan-out). It does not actually *limit* to N.

### Things NOT to do

- Do not narrow `company_news_lookback_days` — reintroduces a real bug.
- Do not tighten `max_output_tokens` much below 1400 without checking the
  structured agents; truncated JSON makes runs slower, not faster.
- Do not "fix" the 6 baseline test failures.
- Do not edit the main repo or the UI worktree.

---

## Verification habit that paid off here

Twice this session a change *looked* correct and was not:

1. `--fast` existed but `cli/main.py` never called `get_fast_config()` — the
   flag did nothing.
2. The fan-in passed tests but broke in production because the tests didn't
   reproduce staggered timing.

Both were caught by checking the **actual observable behaviour** (does the
kwarg reach the model object? does the node run exactly once under staggered
timing?) rather than trusting that the code read correctly. Prefer that over
reasoning about what LangGraph "should" do — I asserted a wrong claim about
its fan-in semantics in a code comment and it cost a production error.
