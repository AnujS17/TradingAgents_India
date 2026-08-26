# Debate Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat bull_case/bear_case markdown blobs on the research page with a topic-paired ledger — one row per debate topic, bull's point and bear's point side by side.

**Architecture:** A new one-shot structured-output LLM call (`DebateLedgerExtractor`, mirroring the existing `SignalProcessor`/`Reflector` helper-class pattern) reads the finished `bull_history`/`bear_history` after the debate loop concludes and pairs them into topic rows — `bull_researcher.py`/`bear_researcher.py` are never touched. The result must persist at write time (it costs a real LLM call, unlike the earlier news-sources feature's free read-time parse), which means the first schema migration this codebase has needed — a guarded `ALTER TABLE` inside the existing `create_tables()`.

**Tech Stack:** Python/Pydantic/LangChain structured output (unchanged versions), SQLAlchemy raw SQL for the migration step, React/Next.js (frontend, unchanged) — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-19-debate-ledger-design.md`. Read it for the full rationale (why post-hoc extraction was chosen over touching the live debate prompts, why this isn't retroactive like news-sources was, why the object stays a live pydantic instance instead of the render-to-markdown-then-reparse pattern `Verdict` uses).

## Global Constraints

- **`tradingagents/agents/researchers/bull_researcher.py` and `bear_researcher.py` must not be modified.** No task in this plan touches them.
- **`DebateLedgerExtractor.extract()` must never raise to its caller.** Any failure (unsupported provider, malformed structured response, transient error) returns `DebateLedger(topics=[])`, never propagates.
- **`RunDetail.debate_ledger` is always a list, never `None`.**
- **The DB migration step must be idempotent** (safe to run on every process startup) **and must surface, not swallow, a genuine failure** (an ALTER TABLE that fails for an unexpected reason must raise, not be caught-and-ignored — a silently-missing column makes every future `mark_completed()` call fail later, which is worse and harder to diagnose).
- **`DebateLedger.tsx` renders nothing (not a placeholder) when its input list is empty** — same pattern as `RunHistoryPanel`/`SourcesPanel`.
- **Never add `Co-Authored-By: Claude` or any AI attribution** to commits.
- Existing money-affecting API contract rules (`Verdict`/`TradeLevels` null-handling, 200 vs 202, rate-limit body) are unaffected by this change — do not touch `Verdict`, `TradeLevels`, or their extraction logic while editing `api/schemas.py`/`api/service.py`.
- **Not retroactive.** Runs completed before this ships have `debate_ledger = []` permanently (the column is `NULL` for them) — this is expected, not a bug to fix.

## File Structure

- Modify: `tradingagents/agents/schemas.py` — add `LedgerTopic`, `DebateLedger`.
- Create: `tradingagents/graph/debate_ledger.py` — `DebateLedgerExtractor`.
- Create: `tests/test_debate_ledger_extractor.py`.
- Modify: `api/service.py` — `run_analysis()` returns a 3-tuple, calls the extractor.
- Modify: `api/schemas.py` — mirror `LedgerTopic`/`DebateLedger` on the wire side, add `RunDetail.debate_ledger`.
- Modify: `api/db.py` — `Run.debate_ledger` column, guarded migration in `create_tables()`.
- Modify: `api/store.py` — `mark_completed()` gains a parameter, `_to_detail()` reads the column.
- Modify: `api/worker.py` — updated call site for the 3-tuple and the new `mark_completed` arg.
- Create: `tests/test_debate_ledger_migration.py`.
- Create: `tests/test_store_debate_ledger.py`.
- Modify: `web/app/src/lib/api-client/types.gen.ts` (regenerated), `client.ts` (export types).
- Modify: `web/app/src/app/globals.css` — port `.ledger`/`.ledger__head`/`.duel*` CSS.
- Create: `web/app/src/components/research/DebateLedger.tsx`.
- Create: `web/app/tests/unit/DebateLedger.test.tsx`.
- Modify: `web/app/src/components/research/ReportsRecord.tsx` — remove `bull_case`/`bear_case` from the rendered order.
- Modify: `web/app/src/components/RunView.tsx` — mount `DebateLedger`.

---

### Task 1: Agent-side schema + extractor

**Files:**
- Modify: `tradingagents/agents/schemas.py`
- Create: `tradingagents/graph/debate_ledger.py`
- Create: `tests/test_debate_ledger_extractor.py`

**Interfaces:**
- Produces: `LedgerTopic` (pydantic: `topic: str`, `bull_point: str | None`, `bear_point: str | None`), `DebateLedger` (pydantic: `topics: list[LedgerTopic]`), `DebateLedgerExtractor(quick_thinking_llm).extract(bull_history: str, bear_history: str) -> DebateLedger`.
- Consumes: `bind_structured` from `tradingagents/agents/utils/structured.py` (existing, unchanged).

- [ ] **Step 1: Add the schema**

In `tradingagents/agents/schemas.py`, add near the other structured-output schemas (after the shared rating types, before the Research Manager section, or any similarly-grouped location — follow the file's existing section-comment convention):

```python
# ---------------------------------------------------------------------------
# Debate ledger (post-hoc extraction, not a live debate-agent schema)
# ---------------------------------------------------------------------------


class LedgerTopic(BaseModel):
    """One row of the topic-by-topic bull/bear ledger.

    Extracted after the debate concludes by DebateLedgerExtractor
    (tradingagents/graph/debate_ledger.py) — this is not something either
    the bull or bear researcher agent produces directly.
    """

    topic: str = Field(
        description="Short label for the debated point, e.g. 'RSI reading', "
        "'Free cash flow', 'Revenue growth'."
    )
    bull_point: str | None = Field(
        default=None,
        description="The bull analyst's argument on this topic, paraphrased "
        "concisely. Null if the bull side never raised this topic.",
    )
    bear_point: str | None = Field(
        default=None,
        description="The bear analyst's argument on this topic, paraphrased "
        "concisely. Null if the bear side never raised this topic.",
    )


class DebateLedger(BaseModel):
    """The full set of ledger rows for one debate. Empty means extraction
    found nothing or failed — never a fabricated row."""

    topics: list[LedgerTopic] = Field(default_factory=list)
```

- [ ] **Step 2: Write the failing extractor tests**

Create `tests/test_debate_ledger_extractor.py`:

```python
"""Guard for tradingagents.graph.debate_ledger's post-hoc ledger extractor.

DebateLedgerExtractor never touches the live bull/bear researcher prompts
-- it makes one additional structured-output call after their debate has
already concluded, reading the finished history text. These tests use a
fake LLM (no real provider call) to verify the wiring and, critically,
the never-raise contract.
"""

import pytest

from tradingagents.agents.schemas import DebateLedger, LedgerTopic
from tradingagents.graph.debate_ledger import DebateLedgerExtractor


class _FakeStructuredLLM:
    """Stands in for llm.with_structured_output(DebateLedger)."""

    def __init__(self, result=None, raise_on_invoke=False):
        self._result = result
        self._raise = raise_on_invoke
        self.last_prompt = None

    def invoke(self, prompt):
        self.last_prompt = prompt
        if self._raise:
            raise RuntimeError("provider exploded")
        return self._result


class _FakeLLM:
    """Stands in for the raw LLM passed to bind_structured."""

    def __init__(self, structured_llm):
        self._structured_llm = structured_llm

    def with_structured_output(self, schema):
        assert schema is DebateLedger
        return self._structured_llm


@pytest.mark.unit
def test_returns_the_structured_ledger_on_success():
    expected = DebateLedger(
        topics=[LedgerTopic(topic="Valuation", bull_point="Cheap on FCF.", bear_point="Expensive on P/E.")]
    )
    fake_structured = _FakeStructuredLLM(result=expected)
    extractor = DebateLedgerExtractor(_FakeLLM(fake_structured))

    ledger = extractor.extract("Bull Analyst: ...", "Bear Analyst: ...")

    assert ledger == expected
    assert "Bull Analyst" in fake_structured.last_prompt
    assert "Bear Analyst" in fake_structured.last_prompt


@pytest.mark.unit
def test_never_raises_when_structured_call_fails():
    fake_structured = _FakeStructuredLLM(raise_on_invoke=True)
    extractor = DebateLedgerExtractor(_FakeLLM(fake_structured))

    ledger = extractor.extract("bull text", "bear text")

    assert ledger == DebateLedger(topics=[])


@pytest.mark.unit
def test_never_raises_when_provider_does_not_support_structured_output():
    class _UnsupportedLLM:
        def with_structured_output(self, schema):
            raise NotImplementedError("this provider has no structured mode")

    extractor = DebateLedgerExtractor(_UnsupportedLLM())

    ledger = extractor.extract("bull text", "bear text")

    assert ledger == DebateLedger(topics=[])


@pytest.mark.unit
def test_returns_empty_ledger_when_structured_call_returns_wrong_type():
    # A malformed/unexpected provider response is not a DebateLedger instance.
    fake_structured = _FakeStructuredLLM(result={"not": "a DebateLedger"})
    extractor = DebateLedgerExtractor(_FakeLLM(fake_structured))

    ledger = extractor.extract("bull text", "bear text")

    assert ledger == DebateLedger(topics=[])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_debate_ledger_extractor.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'tradingagents.graph.debate_ledger'`).

- [ ] **Step 4: Implement the extractor**

Create `tradingagents/graph/debate_ledger.py`:

```python
"""Post-hoc extraction of a topic-by-topic bull/bear ledger.

DebateLedgerExtractor is NOT a LangGraph node and is never wired into
bull_researcher.py/bear_researcher.py's live debate loop -- it is a plain
helper, same shape as SignalProcessor (signal_processing.py) and
Reflector (reflection.py), invoked once by the caller (api/service.py)
after the debate has already concluded. This keeps the tuned, working
debate prompts completely untouched while still producing a real,
grounded (not fabricated) topic-paired view of what was actually argued.
"""

from __future__ import annotations

import logging
from typing import Any

from tradingagents.agents.schemas import DebateLedger
from tradingagents.agents.utils.structured import bind_structured

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """You are reconciling a completed investment debate into a topic-by-topic ledger so a reader can compare both sides at a glance.

Below are the full bull and bear conversation histories from a multi-round debate about whether to invest in a stock. Read both sides and identify the distinct points of disagreement or discussion -- one row per topic (e.g. "valuation", "free cash flow", "RSI reading", "balance sheet").

For each topic, extract the bull side's point and the bear side's point in their own words, paraphrased concisely. Do not invent or exaggerate a claim neither side actually made. If only one side addressed a topic, leave the other side's field null -- do not fabricate a counterpoint for it. Produce one row per genuinely distinct topic; do not split one argument into several rows, and do not merge unrelated points into one row.

Bull conversation history:
{bull_history}

Bear conversation history:
{bear_history}
"""


class DebateLedgerExtractor:
    """Reads a finished bull/bear debate and pairs it into topic rows."""

    def __init__(self, quick_thinking_llm: Any):
        self.quick_thinking_llm = quick_thinking_llm

    def extract(self, bull_history: str, bear_history: str) -> DebateLedger:
        """Never raises. Any failure yields an empty ledger."""
        structured_llm = bind_structured(
            self.quick_thinking_llm, DebateLedger, "Debate Ledger Extractor"
        )
        if structured_llm is None:
            return DebateLedger(topics=[])

        prompt = _PROMPT_TEMPLATE.format(
            bull_history=bull_history or "(no bull arguments recorded)",
            bear_history=bear_history or "(no bear arguments recorded)",
        )

        try:
            result = structured_llm.invoke(prompt)
        except Exception as exc:  # noqa: BLE001 - never let extraction fail the run
            logger.warning("Debate Ledger Extractor: structured call failed (%s)", exc)
            return DebateLedger(topics=[])

        if not isinstance(result, DebateLedger):
            logger.warning(
                "Debate Ledger Extractor: structured call returned %s, expected DebateLedger",
                type(result).__name__,
            )
            return DebateLedger(topics=[])

        return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_debate_ledger_extractor.py -v`
Expected: PASS, all 4 tests.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/schemas.py tradingagents/graph/debate_ledger.py tests/test_debate_ledger_extractor.py
git commit -m "feat(agents): add post-hoc debate ledger extractor"
```

---

### Task 2: Wire into run_analysis + mirror the API schema

**Files:**
- Modify: `api/service.py`
- Modify: `api/schemas.py`

**Interfaces:**
- Consumes: `DebateLedgerExtractor`, `DebateLedger`, `LedgerTopic` (Task 1).
- Produces: `run_analysis(...) -> tuple[Verdict, Reports, DebateLedger]` (api-side `DebateLedger`, converted from the agent-side one). `RunDetail.debate_ledger: list[LedgerTopic]`.

- [ ] **Step 1: Add the API-side schema**

In `api/schemas.py`, add after `class Reports(BaseModel): ...` (or, if Task 1 of the news-sources plan already added `NewsSource` there, immediately after it — keep the file's existing grouping):

```python
class LedgerTopic(BaseModel):
    """Wire mirror of tradingagents.agents.schemas.LedgerTopic. Kept
    separate on purpose (api/schemas.py's own module docstring: the wire
    contract must not couple to the agents' structured-output contract)."""

    topic: str
    bull_point: str | None = None
    bear_point: str | None = None
```

In `class RunDetail(RunSummary):`, add after `news_sources: list[NewsSource] = Field(...)` (or after `reports` if the news-sources field is not present in this checkout — follow whatever the current field order is):

```python
    debate_ledger: list[LedgerTopic] = Field(
        default_factory=list,
        description="Topic-by-topic bull/bear pairing, extracted once after "
        "the debate concludes. Always a list — empty means no ledger was "
        "produced (extraction failure, or a run older than this feature), "
        "not an error. Not retroactive: pre-existing runs stay empty "
        "permanently.",
    )
```

- [ ] **Step 2: Wire the extractor into `run_analysis`**

In `api/service.py`, add the import (inside `run_analysis`, matching the existing lazy-import style for `tradingagents` — see `build_config`'s `from tradingagents.default_config import ...` and this function's own `from tradingagents.graph.trading_graph import TradingAgentsGraph`):

```python
def run_analysis(
    ticker: str,
    analysis_date: Date,
    profile: AnalysisProfile,
    refresh_data: bool = False,
) -> tuple[Verdict, Reports, DebateLedger]:
    """Execute one full analysis. Blocking, minutes long, worker-only.

    Note the engine freezes its own inputs per (ticker, date) via
    ``dataflows.snapshot_cache``, so a second run of the same ticker and date
    re-uses the first run's news, filings and market snapshot and only repeats
    the LLM reasoning. That is a separate layer from the run cache above it,
    which skips the reasoning too.
    """
    from tradingagents.graph.debate_ledger import DebateLedgerExtractor
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = build_config(profile)
    # refresh_data=True busts the day's snapshot so news/filings/social are
    # re-fetched. Left False, a repeat run re-reasons over IDENTICAL inputs,
    # which is what makes two runs comparable — any difference is the model,
    # not the data.
    config["snapshot_cache_enabled"] = not refresh_data

    graph = TradingAgentsGraph(config=config)
    final_state, _signal = graph.propagate(ticker, str(analysis_date))

    debate_state = final_state.get("investment_debate_state") or {}
    agent_ledger = DebateLedgerExtractor(graph.quick_thinking_llm).extract(
        debate_state.get("bull_history", ""), debate_state.get("bear_history", "")
    )
    ledger = DebateLedger(
        topics=[
            LedgerTopic(topic=t.topic, bull_point=t.bull_point, bear_point=t.bear_point)
            for t in agent_ledger.topics
        ]
    )

    return _extract_verdict(final_state), _extract_reports(final_state), ledger
```

Add `DebateLedger` and `LedgerTopic` to `api/service.py`'s existing top-level import from `api.schemas`:

```python
from api.schemas import AnalysisProfile, DebateLedger, LedgerTopic, Reports, TradeLevels, Verdict
```

- [ ] **Step 3: Run the existing service tests**

Run: `python -m pytest tests/test_api_verdict_parsing.py -v`
Expected: PASS — `_extract_verdict`/`_extract_reports` are untouched, this confirms the signature change didn't break their existing coverage. (No new test is written in this task; Task 1's tests already cover `DebateLedgerExtractor` in isolation, and `run_analysis`'s wiring is covered end-to-end by Task 3's store test and the worker's own integration — adding a mocked-graph test here would duplicate that coverage for a 6-line wiring change.)

- [ ] **Step 4: Commit**

```bash
git add api/service.py api/schemas.py
git commit -m "feat(api): wire debate ledger extraction into run_analysis"
```

---

### Task 3: DB migration + store wiring

**Files:**
- Modify: `api/db.py`
- Modify: `api/store.py`
- Modify: `api/worker.py`
- Create: `tests/test_debate_ledger_migration.py`
- Create: `tests/test_store_debate_ledger.py`

**Interfaces:**
- Consumes: `DebateLedger`, `LedgerTopic` (Task 2, `api/schemas.py`), `run_analysis`'s 3-tuple return (Task 2).
- Produces: `Run.debate_ledger` DB column, `RunStore.mark_completed(run_id, verdict, reports, debate_ledger)`, `RunDetail.debate_ledger` populated on every read.

- [ ] **Step 1: Add the column**

In `api/db.py`, add to `class Run(Base):`, immediately after the existing `reports` column:

```python
    # Populated once, at write time, by a post-hoc LLM extraction step
    # (api/service.py::run_analysis) — unlike verdict/reports, this is not
    # free to recompute on read, so it must be persisted. NULL for any run
    # created before this column existed; that is expected, not a bug (see
    # docs/superpowers/specs/2026-08-19-debate-ledger-design.md).
    debate_ledger: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 2: Write the failing migration test**

Create `tests/test_debate_ledger_migration.py`. **This codebase has no
pytest-asyncio** — confirmed by reading `tests/test_api_worker.py`, the
only existing suite that exercises `SqlRunStore` against a real SQLite
file: every test there is a plain sync `def test_...`, wrapping async
calls with a local `asyncio.run()` helper. Follow that exact convention,
not `@pytest.mark.asyncio`:

```python
"""Guard for api.db's guarded ALTER TABLE migration.

create_tables()'s own pre-existing docstring says plainly: "Introduce
Alembic before there is data worth preserving — this cannot alter an
existing table." This is the first column this codebase has ever needed
to add to an existing table, so create_tables() must now do that itself,
idempotently, without Alembic. These tests exercise it against a real
on-disk SQLite file (not mocked) so a broken migration is caught here,
not the first time a worker tries to write a debate_ledger to a
pre-existing runs table.

No pytest-asyncio in this codebase (see tests/test_api_worker.py) — async
calls are wrapped with a plain asyncio.run() helper inside sync test
functions, matching that file's established convention.

Also note: Settings (api/settings.py) uses env_prefix="TRADINGAGENTS_API_",
so the real environment variable is TRADINGAGENTS_API_DATABASE_URL, not
bare DATABASE_URL -- and get_settings() is @lru_cache'd, with its own
docstring saying tests must call get_settings.cache_clear() after
patching the environment. Getting either of those wrong makes these
tests silently run against the real default database
(~/.tradingagents/api.db) instead of the intended temp file.
"""

import asyncio
import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import api.db as db_module
from api.db import create_tables
from api.settings import get_settings


def _run(coro):
    return asyncio.run(coro)


def _reset_engine_globals():
    db_module._engine = None
    db_module._sessionmaker = None
    get_settings.cache_clear()


@pytest.fixture
def old_schema_db(tmp_path, monkeypatch):
    """A runs table as it existed BEFORE this migration — no debate_ledger
    column — to prove create_tables() can add the column to real,
    pre-existing data rather than only ever creating a fresh table."""
    db_path = tmp_path / "old.db"
    raw_conn = sqlite3.connect(str(db_path))
    raw_conn.execute(
        """
        CREATE TABLE runs (
            id VARCHAR(32) PRIMARY KEY,
            ticker VARCHAR(32),
            analysis_date DATE,
            profile VARCHAR(16),
            status VARCHAR(16),
            created_at DATETIME,
            started_at DATETIME,
            completed_at DATETIME,
            error TEXT,
            verdict JSON,
            reports JSON,
            refresh_data BOOLEAN,
            requested_by VARCHAR(64)
        )
        """
    )
    raw_conn.execute(
        "INSERT INTO runs (id, ticker, analysis_date, profile, status, created_at, refresh_data) "
        "VALUES ('r1', 'TCS.NS', '2026-08-01', 'fast', 'completed', '2026-08-01T00:00:00+00:00', 0)"
    )
    raw_conn.commit()
    raw_conn.close()

    monkeypatch.setenv("TRADINGAGENTS_API_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    _reset_engine_globals()
    yield db_path
    _reset_engine_globals()


def _columns(db_path) -> list[str]:
    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.connect() as conn:
            result = await conn.execute(text("PRAGMA table_info(runs)"))
            names = [row[1] for row in result.fetchall()]
        await engine.dispose()
        return names

    return _run(scenario())


@pytest.mark.unit
def test_adds_debate_ledger_column_to_a_pre_existing_table(old_schema_db):
    _run(create_tables())

    assert "debate_ledger" in _columns(old_schema_db)


@pytest.mark.unit
def test_pre_existing_row_survives_the_migration(old_schema_db):
    _run(create_tables())

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{old_schema_db}")
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT id, ticker, debate_ledger FROM runs WHERE id = 'r1'"))
            row = result.fetchone()
        await engine.dispose()
        return row

    row = _run(scenario())
    assert row is not None
    assert row[0] == "r1"
    assert row[1] == "TCS.NS"
    assert row[2] is None


@pytest.mark.unit
def test_running_the_migration_twice_is_a_no_op(old_schema_db):
    _run(create_tables())
    _run(create_tables())  # must not raise "duplicate column" on the second run

    assert _columns(old_schema_db).count("debate_ledger") == 1


@pytest.mark.unit
def test_create_tables_still_creates_a_fresh_table_from_nothing(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh.db"
    monkeypatch.setenv("TRADINGAGENTS_API_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    _reset_engine_globals()

    _run(create_tables())

    columns = _columns(db_path)
    _reset_engine_globals()

    assert "debate_ledger" in columns
    assert "verdict" in columns
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_debate_ledger_migration.py -v`
Expected: FAIL — `debate_ledger` is not yet a real column create_tables() adds (Step 1 only declared it on the ORM model, which is enough for `create_tables_still_creates_a_fresh_table_from_nothing` to pass since `create_all` handles brand-new tables already, but the pre-existing-table tests must fail until Step 4's migration logic exists).

- [ ] **Step 4: Implement the guarded migration**

In `api/db.py`, add the `text` import to the existing `from sqlalchemy import (...)` block, and replace `create_tables()`:

```python
from sqlalchemy import (
    JSON,
    Boolean,
    Date as SADate,
    DateTime,
    Index,
    String,
    Text,
    event,
    text,
)
```

```python
async def create_tables() -> None:
    """Create the schema if absent, and add any columns a pre-existing
    ``runs`` table is missing.

    Still adequate while the schema is moving daily and Alembic would be
    overkill — but ``create_all`` alone cannot alter an existing table, and
    debate_ledger (added after this codebase already had real run data) is
    the first column that needed exactly that. Runs a lightweight, guarded
    ALTER TABLE instead: safe to call on every process startup, a no-op
    once the column exists, and does NOT swallow a genuine failure — an
    ALTER TABLE that fails for an unexpected reason must be visible at
    startup, not silently leave the column missing for every later
    mark_completed() call to fail against instead.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        result = await conn.execute(text("PRAGMA table_info(runs)"))
        existing_columns = {row[1] for row in result.fetchall()}
        if "debate_ledger" not in existing_columns:
            await conn.execute(text("ALTER TABLE runs ADD COLUMN debate_ledger JSON"))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_debate_ledger_migration.py -v`
Expected: PASS, all 4 tests.

- [ ] **Step 6: Write the failing store-wiring test**

Create `tests/test_store_debate_ledger.py`. For the persistence round-trip
test, follow `tests/test_api_worker.py`'s established `store` fixture +
`_run()` helper exactly (real on-disk SQLite per test, no
pytest-asyncio, no `create_tables()`/env-var dance needed here — the
fixture builds the engine directly and calls `Base.metadata.create_all`,
which already includes the `debate_ledger` column since Task 3 Step 1
added it to the ORM model):

```python
"""Guard that RunStore.mark_completed persists debate_ledger and
_to_detail() reads it back — Task 1/2 tested the extractor and the
wire-schema in isolation; this tests the persistence round-trip.

No pytest-asyncio in this codebase — see tests/test_api_worker.py, whose
store fixture + asyncio.run() helper this file's persistence test reuses
verbatim.
"""

import asyncio
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import Base, Run
from api.schemas import AnalysisProfile, DebateLedger, LedgerTopic, Reports, Verdict
from api.store import SqlRunStore, _to_detail


def _row(**overrides) -> Run:
    defaults = dict(
        id="r1",
        ticker="EXAMPLE.NS",
        analysis_date=date(2026, 8, 1),
        profile="fast",
        status="completed",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        error=None,
        verdict=None,
        reports=None,
        debate_ledger=None,
        refresh_data=False,
        requested_by=None,
    )
    defaults.update(overrides)
    return Run(**defaults)


@pytest.mark.unit
def test_to_detail_populates_debate_ledger_when_present():
    ledger_json = DebateLedger(
        topics=[LedgerTopic(topic="Valuation", bull_point="Cheap.", bear_point="Expensive.")]
    ).model_dump()

    detail = _to_detail(_row(debate_ledger=ledger_json))

    assert len(detail.debate_ledger) == 1
    assert detail.debate_ledger[0].topic == "Valuation"


@pytest.mark.unit
def test_to_detail_returns_empty_list_when_debate_ledger_column_is_null():
    detail = _to_detail(_row(debate_ledger=None))

    assert detail.debate_ledger == []


@pytest.fixture
def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield SqlRunStore(sessionmaker=maker)
    asyncio.run(engine.dispose())


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
def test_mark_completed_persists_debate_ledger(store):
    async def scenario():
        created = await store.create("EXAMPLE.NS", date(2026, 8, 1), AnalysisProfile.FAST)
        ledger = DebateLedger(topics=[LedgerTopic(topic="Growth", bull_point="Strong.", bear_point="Slowing.")])
        await store.mark_completed(created.id, Verdict(), Reports(), ledger)
        return await store.get(created.id)

    fetched = _run(scenario())
    assert fetched is not None
    assert len(fetched.debate_ledger) == 1
    assert fetched.debate_ledger[0].topic == "Growth"
```

- [ ] **Step 7: Run test to verify it fails**

Run: `python -m pytest tests/test_store_debate_ledger.py -v`
Expected: FAIL — `_to_detail` doesn't read `debate_ledger` yet, and `mark_completed` doesn't accept a fourth argument yet.

- [ ] **Step 8: Wire the store**

In `api/store.py`, add `DebateLedger`, `LedgerTopic` to the existing `from api.schemas import (...)` block (this file already imports `extract_news_sources` and builds `news_sources` in `_to_detail` from the earlier news-sources plan — leave that line exactly as-is, only add the `debate_ledger=...` line below it). Update `_to_detail`:

```python
def _to_detail(row: Run) -> RunDetail:
    reports = Reports.model_validate(row.reports) if row.reports else None
    return RunDetail(
        id=row.id,
        ticker=row.ticker,
        analysis_date=row.analysis_date,
        profile=AnalysisProfile(row.profile),
        status=RunStatus(row.status),
        created_at=row.created_at,
        completed_at=row.completed_at,
        error=row.error,
        verdict=Verdict.model_validate(row.verdict) if row.verdict else None,
        reports=reports,
        news_sources=extract_news_sources(reports) if reports else [],
        debate_ledger=(
            DebateLedger.model_validate(row.debate_ledger).topics
            if row.debate_ledger
            else []
        ),
    )
```

Update `mark_completed`:

```python
    async def mark_completed(
        self, run_id: str, verdict: Verdict, reports: Reports, debate_ledger: DebateLedger
    ) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status=RunStatus.COMPLETED.value,
                    completed_at=utcnow(),
                    verdict=verdict.model_dump(),
                    reports=reports.model_dump(),
                    debate_ledger=debate_ledger.model_dump(),
                )
            )
            await session.commit()
```

- [ ] **Step 9: Update the worker's call site**

In `api/worker.py`, update `execute_run`:

```python
    try:
        # The engine call is synchronous and CPU/IO-bound for minutes. Pushing
        # it to a thread keeps this loop responsive — otherwise the event loop
        # is blocked and nothing else in the process can run, including a
        # clean shutdown.
        verdict, reports, debate_ledger = await asyncio.to_thread(
            run_analysis,
            row.ticker,
            row.analysis_date,
            AnalysisProfile(row.profile),
            row.refresh_data,
        )
    except Exception as exc:  # noqa: BLE001 - record and continue
        logger.exception("run %s failed", row.id)
        await store.mark_failed(row.id, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return

    await store.mark_completed(row.id, verdict, reports, debate_ledger)
    logger.info("completed %s (%s)", row.id, verdict.rating or "no rating")
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `python -m pytest tests/test_store_debate_ledger.py tests/test_debate_ledger_migration.py tests/test_debate_ledger_extractor.py -v`
Expected: PASS, all tests.

- [ ] **Step 11: Run the full backend suite**

Run: `python -m pytest -v`
Expected: PASS — no regressions. (4 pre-existing unrelated failures in `tests/test_adx_dmi_indicators.py` are expected and not this task's concern.)

- [ ] **Step 12: Regenerate the OpenAPI spec**

```bash
python -c "import json; from api.main import app; json.dump(app.openapi(), open('api/openapi.json', 'w'), indent=2)"
git diff --stat api/openapi.json
```

Expected: non-empty diff including `LedgerTopic` and `RunDetail.debate_ledger`.

- [ ] **Step 13: Commit**

```bash
git add api/db.py api/store.py api/worker.py api/openapi.json tests/test_debate_ledger_migration.py tests/test_store_debate_ledger.py
git commit -m "feat(api): persist debate ledger with a guarded schema migration"
```

---

### Task 4: Frontend types + DebateLedger component

**Files:**
- Modify: `web/app/src/lib/api-client/types.gen.ts` (regenerated)
- Modify: `web/app/src/lib/api-client/client.ts`
- Modify: `web/app/src/app/globals.css`
- Create: `web/app/src/components/research/DebateLedger.tsx`
- Create: `web/app/tests/unit/DebateLedger.test.tsx`

**Interfaces:**
- Consumes: `RunDetail.debate_ledger` (Task 3, via regenerated types).
- Produces: `<DebateLedger topics={LedgerTopic[]} />`, mounted by Task 5.

- [ ] **Step 1: Regenerate the typed client**

```bash
cd web/app
npm run generate:api-types
cd ../..
git diff --stat web/app/src/lib/api-client/types.gen.ts
```

Expected: diff shows `LedgerTopic` under `components['schemas']` and `debate_ledger` on `RunDetail`.

- [ ] **Step 2: Export the type**

In `web/app/src/lib/api-client/client.ts`, add:

```ts
export type LedgerTopic = components['schemas']['LedgerTopic'];
```

- [ ] **Step 3: Port the ledger CSS**

In `web/app/src/app/globals.css`, add (near wherever the `.rep*`/`.trace*` block-level styles from the earlier plans live):

```css
/* ── Debate ledger ───────────────────────────────────────────────────
   Ported from web/design/research/index.html:74-113 (the `.ledger`/
   `.duel` structural + typography rules only — this panel does not use
   the mockup's `.fig`/`.trace` inline drill-down buttons, same scoping
   decision as the news-sources panel's CSS port; see docs/superpowers/
   specs/2026-08-19-debate-ledger-design.md). One continuous rule down
   the centre at >=900px, bull left / bear right; below 900px the pairs
   stack and the rule drops. */
.ledger { position: relative; }
@media (min-width: 900px) {
  .ledger::before { content: ""; position: absolute; left: 50%; top: 4px; bottom: 4px; width: 1px;
    background: linear-gradient(180deg, transparent, #D3E1F7 7%, #D3E1F7 93%, transparent); }
}

.duel { display: grid; gap: 10px; }
.duel + .duel { margin-top: 46px; }
.duel__topic { font-family: 'Inter Tight', sans-serif; font-weight: 800; font-size: .8125rem;
               letter-spacing: .02em; color: var(--ink); }
.duel__side { font-family: 'Inter Tight', sans-serif; font-size: .6875rem; font-weight: 900;
              letter-spacing: .09em; }
.duel__bull .duel__side { color: var(--navy); }
.duel__bear .duel__side { color: #1B6FA8; }

.ledger__head { display: none; }

@media (min-width: 900px) {
  .ledger__head { display: grid; grid-template-columns: 1fr 176px 1fr; margin-bottom: 20px; }
  .ledger__head > :first-child { text-align: right; padding-right: 4px; color: var(--navy); }
  .ledger__head > :last-child { padding-left: 4px; color: #1B6FA8; }

  .duel { grid-template-columns: 1fr 176px 1fr; gap: 0; align-items: start; }
  .duel__bull  { grid-column: 1; grid-row: 1; text-align: right; padding-right: 4px; }
  .duel__topic { grid-column: 2; grid-row: 1; text-align: center; background: #fff;
                 padding: 3px 12px; align-self: center; }
  .duel__bear  { grid-column: 3; grid-row: 1; padding-left: 4px; }

  .duel .duel__side { position: absolute; width: 1px; height: 1px; overflow: hidden;
                      clip-path: inset(50%); white-space: nowrap; }
}
```

The `.duel .duel__side { position: absolute; ... }` rule at `>=900px` visually hides the per-row BULL/BEAR labels (the column headers carry that meaning at desktop width) while keeping them in the accessibility tree — do not add `display: none` or drop this rule, it is intentional per the mockup's own comment (`web/design/research/index.html:94-97`).

- [ ] **Step 4: Write the failing component test**

Create `web/app/tests/unit/DebateLedger.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DebateLedger } from '@/components/research/DebateLedger';
import type { LedgerTopic } from '@/lib/api-client/client';

const topics: LedgerTopic[] = [
  { topic: 'Valuation', bull_point: 'Cheap on FCF basis.', bear_point: 'Expensive on trailing P/E.' },
  { topic: 'Order book', bull_point: 'Record order intake this quarter.', bear_point: null },
];

describe('DebateLedger', () => {
  it('renders nothing when topics is empty', () => {
    const { container } = render(<DebateLedger topics={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders one row per topic with both sides shown', () => {
    render(<DebateLedger topics={topics} />);

    expect(screen.getByText('Valuation')).toBeInTheDocument();
    expect(screen.getByText('Cheap on FCF basis.')).toBeInTheDocument();
    expect(screen.getByText('Expensive on trailing P/E.')).toBeInTheDocument();
  });

  it('renders only the populated side when one side is null', () => {
    render(<DebateLedger topics={topics} />);

    expect(screen.getByText('Order book')).toBeInTheDocument();
    expect(screen.getByText('Record order intake this quarter.')).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd web/app && npx vitest run tests/unit/DebateLedger.test.tsx`
Expected: FAIL (`Failed to resolve import "@/components/research/DebateLedger"`).

- [ ] **Step 6: Implement `DebateLedger`**

Create `web/app/src/components/research/DebateLedger.tsx`:

```tsx
import type { LedgerTopic } from '@/lib/api-client/client';

// Topic-by-topic bull/bear pairing, extracted once after the debate
// concludes (see docs/superpowers/specs/2026-08-19-debate-ledger-design.md).
// Renders nothing when empty — an old run (pre-dating this feature) or a
// failed extraction both look the same: no ledger, not a placeholder.
export function DebateLedger({ topics }: { topics: LedgerTopic[] }) {
  if (topics.length === 0) return null;

  return (
    <section aria-label="Bull vs bear ledger" className="mt-8 rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9">
      <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">The debate, topic by topic</h2>
      <p className="copy text-[#6F6F6F] mt-1 measure">
        Where the bull and bear cases actually disagreed, paired side by side.
      </p>

      <div className="ledger mt-10">
        <div className="ledger__head">
          <p className="duel__side">BULL</p>
          <p></p>
          <p className="duel__side">BEAR</p>
        </div>

        {topics.map((item, index) => (
          <div className="duel" key={`${item.topic}-${index}`}>
            <p className="duel__topic">{item.topic}</p>
            {item.bull_point && (
              <div className="duel__bull">
                <p className="duel__side">BULL</p>
                <p className="copy text-[#2C3242] mt-2">{item.bull_point}</p>
              </div>
            )}
            {item.bear_point && (
              <div className="duel__bear">
                <p className="duel__side">BEAR</p>
                <p className="copy text-[#2C3242] mt-2">{item.bear_point}</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd web/app && npx vitest run tests/unit/DebateLedger.test.tsx`
Expected: PASS, all 3 tests.

- [ ] **Step 8: Commit**

```bash
git add web/app/src/lib/api-client/types.gen.ts web/app/src/lib/api-client/client.ts \
        web/app/src/app/globals.css web/app/src/components/research/DebateLedger.tsx \
        web/app/tests/unit/DebateLedger.test.tsx
git commit -m "feat(web): add DebateLedger component"
```

---

### Task 5: Mount, de-duplicate ReportsRecord, and verify

**Files:**
- Modify: `web/app/src/components/research/ReportsRecord.tsx`
- Modify: `web/app/src/components/RunView.tsx`

**Interfaces:**
- Consumes: `DebateLedger` (Task 4), `current.debate_ledger` (Task 3, via `RunDetail`).

- [ ] **Step 1: Remove bull_case/bear_case from ReportsRecord's rendered order**

In `web/app/src/components/research/ReportsRecord.tsx`, `REPORT_LABELS` keeps all 10 entries unchanged (its type is `Record<keyof Reports, string>`, which requires every key — removing `bull_case`/`bear_case` from it would be a type error; the unused labels are harmless). Change `REPORT_ORDER` to remove them:

```tsx
const REPORT_ORDER: (keyof Reports)[] = [
  'final_decision',
  'investment_plan',
  'trader_plan',
  'risk_debate',
  'market',
  'sentiment',
  'news',
  'fundamentals',
];
```

Change `TOTAL_REPORT_FIELDS` from `10` to `8` (two of the ten `Reports` fields are no longer surfaced in this accordion — they now live in `DebateLedger` instead — and this constant drives the "X of N" header count):

```tsx
const TOTAL_REPORT_FIELDS = 8;
```

- [ ] **Step 2: Mount `DebateLedger`**

In `web/app/src/components/RunView.tsx`, add the import:

```tsx
import { DebateLedger } from './research/DebateLedger';
```

Mount it in the completed-run column, directly after the existing `<SourcesPanel sources={current.news_sources ?? []} />` line:

```tsx
              <SourcesPanel sources={current.news_sources ?? []} />
              <DebateLedger topics={current.debate_ledger ?? []} />
```

The `?? []` mirrors the same optional-field pattern the news-sources plan's Task 4 already established for `current.news_sources` on this exact line — the generated TS type for a pydantic field with a default is `LedgerTopic[] | undefined`, not a plain array.

- [ ] **Step 3: Full verification suite**

Run, from `web/app`:

```bash
npm run build
npm run lint
npx vitest run
npx playwright test
```

Expected: all four green. If any existing Playwright spec's fixture asserts on `ReportsRecord`'s report count or the presence of a bull/bear-case row, update the fixture/assertion to match the new 8-report accordion + separate ledger section — that is an intended consequence of this task, not a regression to work around.

- [ ] **Step 4: Commit**

```bash
git add web/app/src/components/research/ReportsRecord.tsx web/app/src/components/RunView.tsx
git commit -m "feat(web): mount DebateLedger and de-duplicate bull/bear from the report list"
```
