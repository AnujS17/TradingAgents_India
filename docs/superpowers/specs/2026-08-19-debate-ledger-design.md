# Topic-by-Topic Bull/Bear Debate Ledger — Design Spec

## Goal

Replace the flat bull_case/bear_case markdown blobs on the research page
with a real topic-paired ledger — one row per debate topic, bull's point
and bear's point shown side by side — matching the mockup's `.ledger`
pattern. Second of the four features scoped out during the
design-integration effort.

## Background

`bull_researcher.py`/`bear_researcher.py` run a free-flowing, multi-round
conversational debate (`investment_debate_state.bull_history` /
`.bear_history` — plain concatenated paragraphs, no topic tags). Unlike
the news-sources feature, there is no already-persisted structured data
to parse: nothing in this pipeline has ever tagged an argument with a
topic. A real ledger requires generating that structure.

**Decision (user-approved):** post-hoc extraction, not a change to the
live debate prompts. A new, one-shot structured-output LLM call reads the
*finished* `bull_history` and `bear_history` after the debate concludes
and pairs them into topic rows. `bull_researcher.py`/`bear_researcher.py`
are not touched — their tuned, working debate behavior is unaffected.

**Cost/trade-off, stated plainly:** this is not free like news-sources
was. It is one additional LLM call per run (cheap tier), it must run and
persist exactly once (at analysis-completion time, not on every read),
and it does **not** work retroactively — a run completed before this
ships has no ledger until re-run. `RunDetail.debate_ledger` is `[]` for
those, same as `news_sources` before Task 1 shipped, but a genuinely
different, permanent difference: old runs will simply never gain a
ledger, whereas old runs.did gain news_sources.

## Architecture

### 1. Schema — `tradingagents/agents/schemas.py`

```python
class LedgerTopic(BaseModel):
    topic: str = Field(description="Short label for the debated point, e.g. 'RSI reading', 'Free cash flow', 'Revenue growth'")
    bull_point: str | None = Field(default=None, description="The bull analyst's argument on this topic, or null if the bull side never raised it")
    bear_point: str | None = Field(default=None, description="The bear analyst's argument on this topic, or null if the bear side never raised it")


class DebateLedger(BaseModel):
    topics: list[LedgerTopic] = Field(default_factory=list)
```

No render-to-markdown/reparse step (unlike `Verdict`'s extraction — see
`api/service.py::_extract_verdict`'s docstring for why that pattern
exists there). This object is consumed once, directly, by
`api/service.py` — it never needs to become markdown for another agent
to read, so keeping it as a live pydantic object end-to-end is simpler
and has no reparse-fragility risk.

### 2. Extractor — `tradingagents/graph/debate_ledger.py` (new)

Same shape as the existing `SignalProcessor`/`Reflector` helper classes
(`tradingagents/graph/signal_processing.py`, `.../reflection.py`) —
plain class, not a LangGraph node, invoked directly by the caller after
the graph run finishes:

```python
class DebateLedgerExtractor:
    def __init__(self, quick_thinking_llm):
        self.quick_thinking_llm = quick_thinking_llm

    def extract(self, bull_history: str, bear_history: str) -> DebateLedger:
        ...
```

Uses the existing `bind_structured`/`invoke_structured_or_freetext`
pattern (`tradingagents/agents/utils/structured.py`, same one
`sentiment_analyst.py` uses) so it works across providers (native
structured output where supported, free-text-then-parse fallback
otherwise). Prompt instructs the model to read both full histories and
produce one row per distinct point either side raised, pairing a bull
and bear point under the same topic where they actually addressed the
same thing, leaving one side null where only one side raised a point.

If the structured call fails outright (bad response, provider error) —
catch and return an empty `DebateLedger(topics=[])`, never raise. This
must never fail or block the run itself; a missing ledger degrades to
"no ledger view," not a failed analysis.

### 3. Wiring — `api/service.py::run_analysis()`

After `graph.propagate()` returns `final_state`, before returning:

```python
debate_state = final_state.get("investment_debate_state") or {}
ledger = DebateLedgerExtractor(graph.quick_thinking_llm).extract(
    debate_state.get("bull_history", ""), debate_state.get("bear_history", "")
)
```

`run_analysis()`'s return signature grows from
`tuple[Verdict, Reports]` to `tuple[Verdict, Reports, DebateLedger]`.
Every caller of `run_analysis()` (the worker) and `RunStore.mark_completed()`
must be updated to carry the third value through to persistence.

### 4. Schema — `api/schemas.py`

Mirror `tradingagents.agents.schemas.LedgerTopic`/`DebateLedger` on the
wire side (same field shape as the existing `Verdict`/`Reports` mirror
pattern — API schemas stay decoupled from agent schemas per
`api/schemas.py`'s own module docstring). `RunDetail` gains:

```python
debate_ledger: list[LedgerTopic] = Field(default_factory=list)
```

### 5. Persistence — `api/db.py` + `api/store.py`

**First schema migration this codebase has needed** (no Alembic, no
existing ALTER-TABLE precedent — `api/db.py` only ever calls
`Base.metadata.create_all`, which does not modify existing tables).

- Add `debate_ledger: Mapped[dict | None] = mapped_column(JSON, nullable=True)`
  to the `Run` model in `api/db.py`, next to `verdict`/`reports`.
- Add a guarded migration step, run once at the same point
  `create_all` already runs: check whether the `runs` table already has
  a `debate_ledger` column (`PRAGMA table_info(runs)` for SQLite), and if
  not, `ALTER TABLE runs ADD COLUMN debate_ledger JSON`. Idempotent —
  safe to run on every startup, a no-op once the column exists. This is
  a minimal, SQLite-specific migration, appropriate to this prototype's
  stated scale (`api/db.py`'s own docstring: "fine for a prototype,
  NOT fine for production concurrency — switch to Postgres before real
  traffic"); a real migration tool is out of scope for this feature.
- `RunStore.mark_completed()` gains a `debate_ledger: DebateLedger`
  parameter, persisted as `debate_ledger.model_dump()`.
- `_to_detail()` reads `row.debate_ledger` (nullable — old rows are
  `None`) and maps it to `RunDetail.debate_ledger`, defaulting to `[]`
  when `None`.

### 6. Frontend — `web/app/src/components/research/DebateLedger.tsx` (new)

- Props: `{ topics: LedgerTopic[] }`.
- Renders nothing when `topics` is empty (old runs, or extraction
  failure) — same null-render convention as `RunHistoryPanel`/
  `SourcesPanel`.
- Ports the mockup's `.ledger`/`.ledger__head`/`.duel` CSS
  (`web/design/research/index.html` — grep `.ledger`/`.duel` for the
  exact rules) into `globals.css`. One row per topic: topic label
  centered, bull point on one side, bear point on the other; a topic
  with only one side populated renders that side only (never fabricate
  the missing side's text).
- Mounted in `RunView.tsx`. Placement: replaces the plain `bull_case`/
  `bear_case` ROWS in `ReportsRecord`'s accordion — those two entries
  come out of `REPORT_ORDER`/`REPORT_LABELS` once this ships (the raw
  full-text bull/bear cases remain readable in full via
  `investment_plan`'s reasoning and `risk_debate`, so nothing is lost,
  just de-duplicated), and `DebateLedger` takes their place as its own
  section, near `SourcesPanel`.

## Data flow

```
debate loop concludes (investment_debate_state.bull_history/bear_history final)
  -> api/service.py::run_analysis(), after graph.propagate()
       -> DebateLedgerExtractor(graph.quick_thinking_llm).extract(...)
       -> DebateLedger (never raises — [] on any failure)
  -> RunStore.mark_completed(..., debate_ledger=...)
  -> api/db.py Run.debate_ledger JSON column (NEW, migrated)
  -> api/store.py::_to_detail() -> RunDetail.debate_ledger
  -> frontend DebateLedger.tsx (renders nothing if empty)
```

## Error handling

- Extraction failure -> empty ledger, run still completes and persists
  normally. Never a new failure mode for the run itself.
- Old runs (pre-migration) -> `debate_ledger` column is `NULL` ->
  `RunDetail.debate_ledger` is `[]` -> panel renders nothing. No crash,
  no fabricated placeholder.
- Migration failure (ALTER TABLE fails for an unexpected reason) should
  surface loudly at startup (not swallowed) — a broken migration
  silently leaving the column missing would make every future
  `mark_completed()` call fail instead, which is a worse, later, harder
  to diagnose failure.

## Testing

- `DebateLedgerExtractor`: unit test with a fake/mock LLM returning a
  known structured response, asserting the parse-through works; a
  separate test asserting a raised/malformed-response case yields
  `DebateLedger(topics=[])` rather than propagating.
- Migration: a test that runs the guarded ALTER-TABLE step twice against
  a fresh SQLite file and asserts no error on the second run (idempotency).
- `RunStore.mark_completed`/`_to_detail`: wiring tests analogous to
  `tests/test_store_news_sources.py`.
- Frontend: `DebateLedger.tsx` render/empty-render tests, matching
  `SourcesPanel.test.tsx`'s pattern.
- No new E2E scenario required unless an existing spec's fixture needs
  a `debate_ledger` key added for realism (optional, matching the
  earlier feature's own deferred E2E-fixture finding).

## Non-goals

- No change to `bull_researcher.py`/`bear_researcher.py`'s live debate
  prompts or behavior.
- No retroactive ledger for pre-existing runs.
- No inline citation linking within the ledger rows (that's the
  evidence-trace v2 item, tracked separately in `tradingagentsv2.md`).
- The structured risk-comparison table (`.rk`, three analysts' differing
  stop-loss levels) and live per-agent status remain out of scope —
  unrelated scoped-out items.

## Global constraints for the implementation plan

- `bull_researcher.py`/`bear_researcher.py` must not be modified.
- `DebateLedgerExtractor.extract()` must never raise to its caller.
- `RunDetail.debate_ledger` is always a list, never `None`.
- The DB migration step must be idempotent and must surface (not
  swallow) a genuine failure.
- `DebateLedger.tsx` renders nothing (not a placeholder) when its input
  is empty.
- Never add `Co-Authored-By: Claude` or any AI attribution to commits.
- Existing money-affecting contract rules (`Verdict`/`TradeLevels` null
  handling, 200 vs 202, rate-limit body) are unaffected — do not touch
  them while editing `api/schemas.py`/`api/service.py`.
