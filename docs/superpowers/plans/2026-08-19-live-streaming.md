# Live LLM Response Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream each agent's LLM response, token by token, to the research page while a run is in progress, instead of only revealing results once the run completes.

**Architecture:** LangGraph 1.2.11's native `stream_mode="messages"` (proven feasible today via the engine's existing `self.debug` branch using `stream_mode="values"`) feeds a new callback (`on_token`) that a worker-side buffered writer persists into a new, ephemeral `run_events` DB table via a plain sync `sqlite3` connection (the worker call runs off the event loop already). The API relays new rows as Server-Sent Events; the browser's native `EventSource` consumes them. Nothing about the existing non-streaming engine path, worker/API process split, or completed-run rendering changes.

**Tech Stack:** LangGraph 1.2.11 (installed, unchanged), stdlib `sqlite3` (worker-side writes, new), FastAPI `StreamingResponse` (already a dependency), browser `EventSource` (built-in, no new frontend dependency).

**Spec:** `docs/superpowers/specs/2026-08-19-live-streaming-design.md`. Read it for the full rationale — why SSE over WebSockets, why a DB table over Redis, why sync sqlite3 over the async engine, why events are ephemeral.

## Global Constraints

- **`TradingAgentsGraph.propagate()`/`_run_graph()` (the existing, non-streaming path) must not be modified.** Every existing test, the CLI's non-debug mode, and `run_analysis()`'s current call site all depend on it unchanged.
- **`on_token` must never raise into the engine's execution.** Any failure in the callback (DB write error, disk full) degrades silently — logged, not propagated. A live-view glitch must never fail a run.
- **`run_events` rows for a run must be deleted once that run reaches `completed` or `failed`.** Never accumulate indefinitely.
- **The worker-side writer uses a plain sync `sqlite3` connection, never the async SQLAlchemy engine.** `execute_run()` calls the engine via `asyncio.to_thread`, off the event loop — the writer runs in that same thread.
- **The SSE endpoint must honor `Last-Event-ID`** so a browser reconnect resumes rather than replaying from the start.
- **Never add `Co-Authored-By: Claude` or any AI attribution** to commits.
- Existing money-affecting API contract rules (`Verdict`/`TradeLevels` null-handling, 200 vs 202, rate-limit body) are unaffected — do not touch them.
- **No completed-run rendering component changes.** `RunView`/`ReportsRecord`/`SourcesPanel`/`DebateLedger` and their tests are out of scope entirely.

## Process notes (carried forward from the prior plan's mid-execution user directive)

Unless the user says otherwise when this plan is executed: implementers reply with a short status summary (no full report.md file), run a focused/reduced test subset rather than the full suite each time, write a reduced test count per task (noted per-task below), and do NOT commit — the controller reviews the diff and asks the user before any commit.

## File Structure

- Modify: `tradingagents/graph/trading_graph.py` — new `propagate_streaming()` method.
- Modify: `api/db.py` — new `RunEvent` table.
- Create: `api/streaming.py` — `RunEventWriter`.
- Modify: `api/store.py` — `get_events_since()`, event-deletion in `mark_completed`/`mark_failed`.
- Modify: `api/service.py` — `run_analysis()` gains an optional `on_token` passthrough parameter.
- Modify: `api/worker.py` — constructs `RunEventWriter`, wires it through.
- Modify: `api/routers/runs.py` — new `GET /runs/{run_id}/stream` SSE endpoint.
- Create: `web/app/src/lib/useRunStream.ts` — `EventSource` hook.
- Create: `web/app/src/components/research/LiveStream.tsx` — live per-node view.
- Modify: `web/app/src/components/research/RunHeader.tsx` (or wherever the in-progress state currently renders — verify exact mount point during Task 6) — mount the live view while `status !== 'completed'`.

---

### Task 1: Engine — `propagate_streaming()`

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`
- Create: `tests/test_propagate_streaming.py`

**Interfaces:**
- Produces: `TradingAgentsGraph.propagate_streaming(company_name, trade_date, asset_type="stock", on_token: Callable[[str, str], None] | None = None) -> dict` (returns the final state dict, same shape `propagate()` returns).
- Consumes: `self.graph.stream(...)`, `self.propagator`, `self.workflow` (all existing).

**Reduced test count for this task: 3 tests** (not an exhaustive suite — cover the callback contract, the never-raise guarantee, and that the final state shape matches `propagate()`'s).

- [ ] **Step 1: Read `_run_graph()` and `get_graph_args()` exactly as they exist today**

Before writing anything, re-read `tradingagents/graph/trading_graph.py`'s `propagate()`/`_run_graph()` (around line 443-542) and `tradingagents/graph/propagation.py`'s `get_graph_args()` (line 91) in the actual checkout — this plan's code below assumes their current shape but the implementer must verify line numbers/exact surrounding code haven't drifted since this plan was written, and adapt the insertion point accordingly without changing either existing method's behavior.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_propagate_streaming.py`. Follow the stubbing precedent in `tests/test_ticker_identity_consistency.py::_graph_with_stubs()` for building a `TradingAgentsGraph` whose `self.graph` is replaced with a fake compiled graph — do not call a real LLM provider. If that precedent's exact stub shape doesn't transfer cleanly, build a minimal fake with a `.stream(initial_state, stream_mode=modes, **kwargs)` method that yields a fixed sequence of `(mode, chunk)` tuples matching what `self.graph.stream(..., stream_mode=["values","messages"])` actually yields (a `"values"` chunk is a partial state dict; a `"messages"` chunk is `(message_chunk_obj, metadata_dict)` where `message_chunk_obj.content` is the token text and `metadata_dict["langgraph_node"]` is the node name — construct simple stand-in objects/dicts with exactly these shapes, not real LangChain message classes).

```python
"""Guard for TradingAgentsGraph.propagate_streaming's callback contract.

Does not call a real LLM provider -- self.graph is replaced with a fake
compiled graph yielding a fixed, hand-built sequence of (stream_mode,
chunk) tuples matching LangGraph's real shape for stream_mode=
["values", "messages"].
"""

import pytest


class _FakeMessageChunk:
    def __init__(self, content: str):
        self.content = content


class _FakeCompiledGraph:
    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, _initial_state, stream_mode=None, **_kwargs):
        for mode, payload in self._chunks:
            yield mode, payload


@pytest.mark.unit
def test_on_token_fires_for_each_messages_chunk_with_node_and_delta():
    chunks = [
        ("values", {"market_report": ""}),
        ("messages", (_FakeMessageChunk("Bull"), {"langgraph_node": "bull_researcher"})),
        ("messages", (_FakeMessageChunk(" case"), {"langgraph_node": "bull_researcher"})),
        ("values", {"market_report": "final text"}),
    ]
    seen = []

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)  # bypass __init__, unit-test internals directly
    graph.graph = _FakeCompiledGraph(chunks)
    graph.propagator = _StubPropagator()
    graph.workflow = None
    graph.config = {}
    graph.debug = False
    graph.memory_log = _StubMemoryLog()
    graph._checkpointer_ctx = None
    graph.ticker = None

    result = graph.propagate_streaming(
        "TESTCO", "2026-08-19", on_token=lambda node, delta: seen.append((node, delta))
    )

    assert seen == [("bull_researcher", "Bull"), ("bull_researcher", " case")]
    assert result == {"market_report": "final text"}


@pytest.mark.unit
def test_on_token_failure_never_raises_into_propagate_streaming():
    chunks = [("messages", (_FakeMessageChunk("x"), {"langgraph_node": "n"}))]

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.graph = _FakeCompiledGraph(chunks)
    graph.propagator = _StubPropagator()
    graph.workflow = None
    graph.config = {}
    graph.debug = False
    graph.memory_log = _StubMemoryLog()
    graph._checkpointer_ctx = None
    graph.ticker = None

    def exploding_callback(_node, _delta):
        raise RuntimeError("db locked")

    # Must not raise, despite the callback exploding on every call.
    graph.propagate_streaming("TESTCO", "2026-08-19", on_token=exploding_callback)


@pytest.mark.unit
def test_on_token_none_behaves_like_no_callback_was_passed():
    chunks = [
        ("messages", (_FakeMessageChunk("x"), {"langgraph_node": "n"})),
        ("values", {"market_report": "done"}),
    ]

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.graph = _FakeCompiledGraph(chunks)
    graph.propagator = _StubPropagator()
    graph.workflow = None
    graph.config = {}
    graph.debug = False
    graph.memory_log = _StubMemoryLog()
    graph._checkpointer_ctx = None
    graph.ticker = None

    result = graph.propagate_streaming("TESTCO", "2026-08-19")  # no on_token

    assert result == {"market_report": "done"}


class _StubPropagator:
    def create_initial_state(self, *_args, **_kwargs):
        return {}

    def get_graph_args(self, *_args, **_kwargs):
        return {"config": {}}


class _StubMemoryLog:
    def get_past_context(self, *_args, **_kwargs):
        return ""
```

Adjust the stub attributes above (`graph.config`, `graph.debug`, etc.) to match whatever `_run_graph()` actually reads in the current checkout — read the real method first (Step 1) and reconcile before finalizing this test file; the point of the test is the callback contract, not a byte-exact replay of every side effect `_run_graph()` performs (snapshot-date setting, memory-log resolution, checkpointer) — stub out or no-op whichever of those `propagate_streaming()` also needs to call, following the same structure `_run_graph()` uses.

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_propagate_streaming.py -v`
Expected: FAIL (`AttributeError: 'TradingAgentsGraph' object has no attribute 'propagate_streaming'`).

- [ ] **Step 4: Implement `propagate_streaming()`**

In `tradingagents/graph/trading_graph.py`, add a new method near `propagate()`/`_run_graph()`, reusing the exact same setup sequence `_run_graph()` uses (ticker resolution, snapshot date, memory-log resolution) — do not duplicate that logic by hand if it can be factored into a shared private helper both `_run_graph()` and this new method call; if extracting a shared helper risks touching `_run_graph()`'s existing behavior, duplicating the setup lines is the safer choice for this task (a small, obviously-inert duplication is preferable to risking the tuned, working path):

```python
def propagate_streaming(self, company_name, trade_date, asset_type: str = "stock", on_token=None):
    """Like propagate(), but also streams token-level chunks through
    on_token(node_name: str, delta: str) as the graph executes.

    on_token is optional; passing None runs identically to propagate()
    with no callback overhead beyond the extra stream_mode. on_token is
    never allowed to raise into this method's control flow — a failing
    callback degrades to "no live view for that chunk," never fails the
    run itself (see docs/superpowers/specs/2026-08-19-live-streaming-design.md).

    Does NOT modify propagate()/_run_graph() -- this is a parallel,
    additive execution path for the worker's streaming call site only.
    """
    company_name = resolve_ticker_symbol(company_name, asset_type)
    self.ticker = company_name

    from tradingagents.dataflows.snapshot_cache import set_snapshot_date

    set_snapshot_date(trade_date)
    self._resolve_pending_entries(company_name)

    past_context = self.memory_log.get_past_context(company_name)
    init_agent_state = self.propagator.create_initial_state(
        company_name, trade_date, asset_type=asset_type, past_context=past_context
    )
    args = self.propagator.get_graph_args()
    args.pop("stream_mode", None)  # this method controls stream_mode itself

    final_state: dict = {}
    for stream_mode, chunk in self.graph.stream(
        init_agent_state, stream_mode=["values", "messages"], **args
    ):
        if stream_mode == "values":
            final_state.update(chunk)
        elif stream_mode == "messages" and on_token is not None:
            message_chunk, metadata = chunk
            node_name = metadata.get("langgraph_node", "unknown")
            delta = getattr(message_chunk, "content", "") or ""
            if delta:
                try:
                    on_token(node_name, delta)
                except Exception as exc:  # noqa: BLE001 - never fail the run over a live-view glitch
                    logger.warning("propagate_streaming: on_token failed (%s)", exc)

    self.curr_state = final_state
    self._log_state(trade_date, final_state)
    return final_state
```

Check the module already has a `logger` (it likely does, given `logger.info(...)` calls already visible in `propagate()`); if not, add `import logging` + `logger = logging.getLogger(__name__)` at module scope, matching the convention already used in `tradingagents/graph/debate_ledger.py`.

Confirm `_log_state` and `_resolve_pending_entries` are safe to call from a second method (they should be — `_run_graph()` already calls them and nothing about their behavior is `propagate()`-call-specific) by reading their bodies before relying on this.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_propagate_streaming.py -v`
Expected: PASS, all 3 tests.

- [ ] **Step 6: Confirm the non-streaming path is untouched**

Run: `git diff tradingagents/graph/trading_graph.py` and visually confirm `propagate()`/`_run_graph()`'s existing lines are unchanged — only new lines were added.

- [ ] **Step 7: Do not commit.** Leave changes in the working tree. Report back per the process notes above.

---

### Task 2: DB table + worker-side writer

**Files:**
- Modify: `api/db.py`
- Create: `api/streaming.py`
- Create: `tests/test_run_event_writer.py`

**Interfaces:**
- Produces: `RunEvent` ORM table, `RunEventWriter(db_path, run_id, flush_interval_s=0.25, flush_chars=200)` with `.on_token(node_name, delta)`, `.flush_all()`, `.close()`.
- Consumes: nothing from Task 1 directly (this task's writer is exercised standalone; Task 4 wires `propagate_streaming`'s `on_token` to `writer.on_token`).

**Reduced test count for this task: 4 tests.**

- [ ] **Step 1: Add the `RunEvent` table**

In `api/db.py`, add `Integer` to the existing `from sqlalchemy import (...)` block, and add the new table class after `class Run(Base): ...`:

```python
class RunEvent(Base):
    """Ephemeral: one run's streamed token chunks, deleted once that run
    reaches completed or failed (see docs/superpowers/specs/
    2026-08-19-live-streaming-design.md). Never a permanent record --
    Reports carries the permanent record."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    node_name: Mapped[str] = mapped_column(String(64))
    text_delta: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_run_events_run_seq", "run_id", "seq"),
    )
```

This is a brand-new table, not a new column on `runs` — `create_tables()`'s existing `Base.metadata.create_all` call creates it automatically on both a fresh DB and an existing one (SQLAlchemy's `create_all` DOES create missing tables, it just cannot ALTER existing ones — the debate-ledger plan's migration only exists for the `debate_ledger` column case, not this one). No migration step needed here.

- [ ] **Step 2: Write the failing writer tests**

Create `tests/test_run_event_writer.py`:

```python
"""Guard for api.streaming.RunEventWriter's buffering/flush behavior.

Uses a real temp sqlite file, not a mock -- the whole point of this
writer is a real, working sync sqlite3 connection.
"""

import sqlite3
import time

import pytest

from api.streaming import RunEventWriter


def _rows(db_path, run_id):
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT node_name, text_delta, seq FROM run_events WHERE run_id = ? ORDER BY seq",
        (run_id,),
    ).fetchall()
    conn.close()
    return rows


@pytest.mark.unit
def test_flushes_when_char_threshold_is_crossed(tmp_path):
    db_path = tmp_path / "events.db"
    writer = RunEventWriter(str(db_path), "run1", flush_interval_s=999, flush_chars=5)

    writer.on_token("market_analyst", "hello")  # exactly at threshold

    assert _rows(db_path, "run1") == [("market_analyst", "hello", 1)]
    writer.close()


@pytest.mark.unit
def test_buffers_below_threshold_until_flush_all(tmp_path):
    db_path = tmp_path / "events.db"
    writer = RunEventWriter(str(db_path), "run1", flush_interval_s=999, flush_chars=100)

    writer.on_token("market_analyst", "hi")
    assert _rows(db_path, "run1") == []  # below threshold, not yet flushed

    writer.flush_all()
    assert _rows(db_path, "run1") == [("market_analyst", "hi", 1)]
    writer.close()


@pytest.mark.unit
def test_separate_nodes_get_separate_buffers_and_increasing_seq(tmp_path):
    db_path = tmp_path / "events.db"
    writer = RunEventWriter(str(db_path), "run1", flush_interval_s=999, flush_chars=1)

    writer.on_token("bull_researcher", "a")
    writer.on_token("bear_researcher", "b")

    rows = _rows(db_path, "run1")
    assert [r[0] for r in rows] == ["bull_researcher", "bear_researcher"]
    assert [r[2] for r in rows] == [1, 2]  # seq increases across the whole run, not per-node
    writer.close()


@pytest.mark.unit
def test_flushes_on_time_threshold(tmp_path):
    db_path = tmp_path / "events.db"
    writer = RunEventWriter(str(db_path), "run1", flush_interval_s=0.05, flush_chars=9999)

    writer.on_token("market_analyst", "x")
    assert _rows(db_path, "run1") == []  # below char threshold

    time.sleep(0.08)
    writer.on_token("market_analyst", "y")  # triggers the time-based flush check

    assert _rows(db_path, "run1") == [("market_analyst", "xy", 1)]
    writer.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_event_writer.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'api.streaming'`).

- [ ] **Step 4: Implement `RunEventWriter`**

Create `api/streaming.py`:

```python
"""Worker-side buffered writer for streamed token chunks.

Deliberately a plain sync sqlite3 connection, not the async SQLAlchemy
engine -- this runs inside api.worker's asyncio.to_thread call, off the
event loop, so there is nothing to gain from the async stack here (see
docs/superpowers/specs/2026-08-19-live-streaming-design.md).
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone


class RunEventWriter:
    def __init__(
        self,
        db_path: str,
        run_id: str,
        flush_interval_s: float = 0.25,
        flush_chars: int = 200,
    ):
        self._conn = sqlite3.connect(db_path)
        self._run_id = run_id
        self._flush_interval_s = flush_interval_s
        self._flush_chars = flush_chars
        self._buffers: dict[str, str] = {}
        self._last_flush_at: dict[str, float] = {}
        self._seq = 0

    def on_token(self, node_name: str, delta: str) -> None:
        self._buffers[node_name] = self._buffers.get(node_name, "") + delta
        last = self._last_flush_at.get(node_name, 0.0)
        crossed_chars = len(self._buffers[node_name]) >= self._flush_chars
        crossed_time = (time.monotonic() - last) >= self._flush_interval_s
        if crossed_chars or crossed_time:
            self._flush_node(node_name)

    def flush_all(self) -> None:
        for node_name in list(self._buffers.keys()):
            self._flush_node(node_name)

    def _flush_node(self, node_name: str) -> None:
        text = self._buffers.get(node_name, "")
        if not text:
            return
        self._seq += 1
        self._conn.execute(
            "INSERT INTO run_events (run_id, seq, node_name, text_delta, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self._run_id, self._seq, node_name, text, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()
        self._buffers[node_name] = ""
        self._last_flush_at[node_name] = time.monotonic()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_event_writer.py -v`
Expected: PASS, all 4 tests.

- [ ] **Step 6: Do not commit.** Report back per the process notes above.

---

### Task 3: Store wiring — event reads + deletion-on-completion

**Files:**
- Modify: `api/store.py`
- Modify: `api/schemas.py` (a small `RunEventOut` response shape for the SSE payload)
- Create: `tests/test_store_run_events.py`

**Interfaces:**
- Produces: `RunStore.get_events_since(run_id, after_seq) -> list[RunEventOut]`; `mark_completed`/`mark_failed` both delete that run's `run_events` rows.
- Consumes: `RunEvent` (Task 2, `api/db.py`).

**Reduced test count for this task: 3 tests.**

- [ ] **Step 1: Add the response schema**

In `api/schemas.py`, add:

```python
class RunEventOut(BaseModel):
    seq: int
    node_name: str
    text_delta: str
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_store_run_events.py`, following the `store`/`_run()` fixture convention from `tests/test_api_worker.py` (reused by the debate-ledger plan's own store tests):

```python
"""Guard for RunStore's run_events read + deletion-on-completion wiring."""

import asyncio
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import Base, RunEvent
from api.schemas import AnalysisProfile, DebateLedger, Reports, Verdict
from api.store import SqlRunStore


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
def test_get_events_since_returns_only_newer_events(store):
    async def scenario():
        created = await store.create("EXAMPLE.NS", date(2026, 8, 1), AnalysisProfile.FAST)
        async with store._sessionmaker() as session:
            session.add_all([
                RunEvent(run_id=created.id, seq=1, node_name="a", text_delta="x", created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
                RunEvent(run_id=created.id, seq=2, node_name="a", text_delta="y", created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
            ])
            await session.commit()
        return await store.get_events_since(created.id, after_seq=1)

    events = _run(scenario())
    assert len(events) == 1
    assert events[0].seq == 2
    assert events[0].text_delta == "y"


@pytest.mark.unit
def test_mark_completed_deletes_that_runs_events(store):
    async def scenario():
        created = await store.create("EXAMPLE.NS", date(2026, 8, 1), AnalysisProfile.FAST)
        async with store._sessionmaker() as session:
            session.add(RunEvent(run_id=created.id, seq=1, node_name="a", text_delta="x", created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
            await session.commit()

        await store.mark_completed(created.id, Verdict(), Reports(), DebateLedger())
        return await store.get_events_since(created.id, after_seq=0)

    assert _run(scenario()) == []


@pytest.mark.unit
def test_mark_failed_deletes_that_runs_events(store):
    async def scenario():
        created = await store.create("EXAMPLE.NS", date(2026, 8, 1), AnalysisProfile.FAST)
        async with store._sessionmaker() as session:
            session.add(RunEvent(run_id=created.id, seq=1, node_name="a", text_delta="x", created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
            await session.commit()

        await store.mark_failed(created.id, "boom")
        return await store.get_events_since(created.id, after_seq=0)

    assert _run(scenario()) == []
```

(The inline `__import__("datetime")` calls are a minor ugliness acceptable for a short test fixture — if it reads badly, add a normal `from datetime import datetime, timezone` import at the top instead; either is fine.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_store_run_events.py -v`
Expected: FAIL — `get_events_since` doesn't exist yet, and `mark_completed`/`mark_failed` don't delete events yet.

- [ ] **Step 4: Implement the store wiring**

In `api/store.py`, add `RunEvent` to the `from api.db import (...)` block and `RunEventOut` to the `from api.schemas import (...)` block. Add:

```python
    async def get_events_since(self, run_id: str, after_seq: int) -> list[RunEventOut]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                .order_by(RunEvent.seq)
            )
            return [
                RunEventOut(seq=row.seq, node_name=row.node_name, text_delta=row.text_delta)
                for row in result.scalars()
            ]
```

In `mark_completed`, add a delete statement in the same transaction, after the `update(Run)...` execute and before `session.commit()`:

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
            await session.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
            await session.commit()
```

Apply the same `await session.execute(delete(RunEvent).where(RunEvent.run_id == run_id))` addition to `mark_failed`, before its existing `session.commit()`. Add `delete` to the existing `from sqlalchemy import select, update` import (`from sqlalchemy import delete, select, update`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_store_run_events.py -v`
Expected: PASS, all 3 tests.

- [ ] **Step 6: Do not commit.** Report back per the process notes above.

---

### Task 4: Wire the worker + `run_analysis`

**Files:**
- Modify: `api/service.py`
- Modify: `api/worker.py`

**Interfaces:**
- Consumes: `propagate_streaming` (Task 1), `RunEventWriter` (Task 2).
- Produces: `run_analysis(..., on_token=None)` — same return shape as before, with token streaming as a side effect when `on_token` is passed.

**No new tests for this task** — it is pure wiring between three already-tested pieces (Task 1's engine method, Task 2's writer, the existing `run_analysis`/`execute_run`), and the existing `tests/test_api_worker.py` suite (11 tests, currently passing per the debate-ledger plan) already exercises `execute_run`'s success/failure/persistence paths end to end; re-running it after this task is the verification.

- [ ] **Step 1: Add `on_token` passthrough to `run_analysis`**

In `api/service.py`, change `run_analysis`'s signature to accept an optional callback and call `propagate_streaming` instead of `propagate` when one is given (falling back to the exact existing call when it isn't, so every current caller/test that doesn't pass `on_token` is unaffected):

```python
def run_analysis(
    ticker: str,
    analysis_date: Date,
    profile: AnalysisProfile,
    refresh_data: bool = False,
    on_token=None,
) -> tuple[Verdict, Reports, DebateLedger]:
    ...
    graph = TradingAgentsGraph(config=config)
    if on_token is not None:
        final_state = graph.propagate_streaming(ticker, str(analysis_date), on_token=on_token)
    else:
        final_state, _signal = graph.propagate(ticker, str(analysis_date))

    debate_state = final_state.get("investment_debate_state") or {}
    ...  # unchanged from here
```

`propagate()` returns a `(final_state, signal)` tuple while `propagate_streaming()` returns just `final_state` (per Task 1's contract) — the `if/else` above already accounts for this; do not try to unify their return shapes, that is an intentional, documented difference (see Task 1's docstring).

- [ ] **Step 2: Wire the worker**

In `api/worker.py`, `execute_run()`:

```python
async def execute_run(store: SqlRunStore, row: Run) -> None:
    from api.service import run_analysis
    from api.streaming import RunEventWriter
    from api.db import _database_url

    logger.info("running %s %s (%s)", row.ticker, row.analysis_date, row.profile)

    writer = RunEventWriter(_sync_db_path(), row.id)
    try:
        verdict, reports, debate_ledger = await asyncio.to_thread(
            run_analysis,
            row.ticker,
            row.analysis_date,
            AnalysisProfile(row.profile),
            row.refresh_data,
            writer.on_token,
        )
    except Exception as exc:  # noqa: BLE001 - record and continue
        logger.exception("run %s failed", row.id)
        writer.flush_all()
        writer.close()
        await store.mark_failed(row.id, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return

    writer.flush_all()
    writer.close()
    await store.mark_completed(row.id, verdict, reports, debate_ledger)
    logger.info("completed %s (%s)", row.id, verdict.rating or "no rating")
```

`RunEventWriter` needs a plain filesystem path to the SQLite file, but `api/db.py`'s `_database_url()` returns a SQLAlchemy URL string (`sqlite+aiosqlite:///...`), not a bare path — add a small helper in `api/worker.py` (or `api/db.py`, whichever reads more naturally once you see the exact current `_database_url()` body) that strips the `sqlite+aiosqlite:///` prefix to get the raw path `sqlite3.connect()` needs:

```python
def _sync_db_path() -> str:
    """RunEventWriter needs a plain filesystem path; _database_url()
    returns a SQLAlchemy async URL. Only supports the sqlite+aiosqlite
    scheme this project actually uses (api/db.py's own docstring: SQLite
    by default, Postgres is a future migration) -- raise clearly rather
    than silently misbehaving if that ever changes."""
    from api.db import _database_url

    url = _database_url()
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise RuntimeError(
            f"RunEventWriter requires a sqlite+aiosqlite database URL, got: {url}"
        )
    return url[len(prefix):]
```

Place this helper wherever it's imported from above (`api/worker.py` is the only caller today, so defining it there is simplest — adjust the `from api.db import _database_url` in `execute_run` and the `_sync_db_path()` call site accordingly if you place it in `api/worker.py` directly rather than importing it).

- [ ] **Step 3: Run the existing worker suite**

Run: `python -m pytest tests/test_api_worker.py -v`
Expected: PASS, all 11 tests — these mock `run_analysis` itself (via `monkeypatch.setattr(api.service, "run_analysis", ...)`), so they never reach `propagate_streaming`/`RunEventWriter` at all; this run confirms the new `on_token` parameter and `RunEventWriter` construction didn't break the existing call shape. If any test's mock lambda signature is now incompatible (e.g. a lambda with a fixed 4-arg signature called with 5 positional args including the new `on_token`), fix that test's lambda to accept the extra argument (`lambda *a, **k: ...` already used throughout that file tolerates this without changes — check each of the 5 mock sites the debate-ledger plan's fix wave already touched).

- [ ] **Step 4: Do not commit.** Report back per the process notes above.

---

### Task 5: SSE endpoint

**Files:**
- Modify: `api/routers/runs.py`
- Create: `tests/test_stream_endpoint.py`

**Interfaces:**
- Consumes: `store.get_events_since` (Task 3).
- Produces: `GET /runs/{run_id}/stream` — `text/event-stream`.

**Reduced test count for this task: 2 tests.**

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stream_endpoint.py`. Check how existing router tests in this project construct a test client against the FastAPI app (search for an existing `tests/test_api_*.py` that hits a router directly, e.g. via `httpx.AsyncClient` or FastAPI's `TestClient`, and match that convention) rather than inventing a new one. The two tests to write:

```python
"""Guard for GET /runs/{run_id}/stream. Follows this project's existing
router-test convention for constructing a client against the app --
check an existing tests/test_api_*.py file for the exact pattern (async
client + dependency override for the store, most likely) and match it
rather than inventing a new harness.
"""

import pytest


@pytest.mark.unit
def test_stream_endpoint_returns_event_stream_media_type():
    """The response Content-Type must be text/event-stream, or a browser
    EventSource will refuse to treat it as SSE."""
    ...  # implementer: wire up per the existing router-test convention


@pytest.mark.unit
def test_stream_closes_after_run_is_marked_completed():
    """A completed run's stream must terminate (send the 'done' event and
    end), not poll forever."""
    ...
```

Write these for real once the existing test-client convention is confirmed — the placeholder `...` bodies above exist only because this plan cannot know that convention without reading the checkout first; do not leave them as `...` in the committed test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_stream_endpoint.py -v`
Expected: FAIL (404, no such route).

- [ ] **Step 3: Implement the endpoint**

In `api/routers/runs.py`, add the imports (`asyncio`, `StreamingResponse` from `fastapi.responses`, `RunStatus` already imported) and the route:

```python
@router.get("/runs/{run_id}/stream", tags=["runs"])
async def stream_run(run_id: str, store: RunStoreDep, request: Request) -> StreamingResponse:
    """Server-Sent Events: token-level live view of an in-progress run.

    Honors Last-Event-ID (sent automatically by a reconnecting browser
    EventSource) so a refresh mid-run resumes rather than replaying from
    the start. Polls run_events via the same WAL-mode SQLite pattern
    api/db.py already documents for concurrent reader/writer access.
    """
    last_seq = int(request.headers.get("Last-Event-ID", "0") or "0")

    async def event_source():
        seq = last_seq
        while True:
            if await request.is_disconnected():
                return
            run = await store.get(run_id)
            if run is None:
                return
            events = await store.get_events_since(run_id, seq)
            for event in events:
                seq = event.seq
                yield f"id: {event.seq}\ndata: {event.model_dump_json()}\n\n"
            if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(event_source(), media_type="text/event-stream")
```

Add `import asyncio` at the top of the file if not already present, and `from fastapi.responses import StreamingResponse`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_stream_endpoint.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Do not commit.** Report back per the process notes above.

---

### Task 6: Frontend hook + live view

**Files:**
- Create: `web/app/src/lib/useRunStream.ts`
- Create: `web/app/src/components/research/LiveStream.tsx`
- Create: `web/app/tests/unit/LiveStream.test.tsx`
- Modify: whichever component currently renders the in-progress ("queued"/"running") state — **verify the exact current mount point by reading `web/app/src/components/research/RunHeader.tsx` and `web/app/src/components/RunView.tsx` in the checkout before editing**, since this plan was written without re-deriving that file's exact current content for this task.

**Interfaces:**
- Produces: `useRunStream(runId: string, enabled: boolean) -> { eventsByNode: Record<string, string> }`, `<LiveStream eventsByNode={...} />`.

**Reduced test count for this task: 2 tests.**

- [ ] **Step 1: Implement the hook**

Create `web/app/src/lib/useRunStream.ts`:

```ts
'use client';

import { useEffect, useRef, useState } from 'react';

const API_BASE_URL =
  typeof window === 'undefined'
    ? process.env.API_BASE_URL ?? 'http://127.0.0.1:8000'
    : process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';

interface RunEventPayload {
  seq: number;
  node_name: string;
  text_delta: string;
}

// Accumulates streamed token deltas per node while a run is in progress.
// `enabled` gates the EventSource lifecycle -- pass `status !== 'completed'
// && status !== 'failed'` from the caller so this closes itself once a run
// finishes, at which point the existing poll-based RunView takes over.
export function useRunStream(runId: string, enabled: boolean) {
  const [eventsByNode, setEventsByNode] = useState<Record<string, string>>({});
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) {
      sourceRef.current?.close();
      sourceRef.current = null;
      return;
    }

    const source = new EventSource(`${API_BASE_URL}/runs/${runId}/stream`);
    sourceRef.current = source;

    source.onmessage = (event) => {
      const payload = JSON.parse(event.data) as RunEventPayload;
      setEventsByNode((prev) => ({
        ...prev,
        [payload.node_name]: (prev[payload.node_name] ?? '') + payload.text_delta,
      }));
    };

    source.addEventListener('done', () => {
      source.close();
    });

    source.onerror = () => {
      // EventSource retries automatically with Last-Event-ID; nothing to
      // do here beyond letting the browser's native reconnect handle it.
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [runId, enabled]);

  return { eventsByNode };
}
```

- [ ] **Step 2: Write the failing component test**

Create `web/app/tests/unit/LiveStream.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LiveStream } from '@/components/research/LiveStream';

describe('LiveStream', () => {
  it('renders nothing when eventsByNode is empty', () => {
    const { container } = render(<LiveStream eventsByNode={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders accumulated text per node', () => {
    render(<LiveStream eventsByNode={{ bull_researcher: 'Bull case building...' }} />);
    expect(screen.getByText(/Bull case building/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web/app && npx vitest run tests/unit/LiveStream.test.tsx`
Expected: FAIL (`Failed to resolve import "@/components/research/LiveStream"`).

- [ ] **Step 4: Implement `LiveStream`**

Create `web/app/src/components/research/LiveStream.tsx`:

```tsx
// Live per-node text view while a run is in progress. Renders nothing
// when there's nothing streamed yet -- same null-render convention as
// SourcesPanel/DebateLedger. Once the run completes, the parent stops
// rendering this (via useRunStream's `enabled` flag) and the normal
// completed-run UI takes over.
export function LiveStream({ eventsByNode }: { eventsByNode: Record<string, string> }) {
  const nodes = Object.entries(eventsByNode);
  if (nodes.length === 0) return null;

  return (
    <section aria-label="Live analysis" className="mt-8 rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9">
      <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">Live</h2>
      <div className="mt-4 grid gap-4">
        {nodes.map(([nodeName, text]) => (
          <div key={nodeName}>
            <p className="font-tight font-bold text-sm text-[#676D80]">{nodeName}</p>
            <p className="copy text-[#2C3242] mt-1 whitespace-pre-wrap">{text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web/app && npx vitest run tests/unit/LiveStream.test.tsx`
Expected: PASS, both tests.

- [ ] **Step 6: Mount it in the in-progress state**

Read `web/app/src/components/research/RunHeader.tsx` and `web/app/src/components/RunView.tsx` in the checkout to find exactly where the "queued"/"running" (non-completed) state currently renders. Mount `<LiveStream eventsByNode={eventsByNode} />` (backed by `useRunStream(current.id, current.status !== 'completed' && current.status !== 'failed')`) inside that branch, alongside whatever status banner already exists there — do not remove or restructure the existing banner, this is additive.

- [ ] **Step 7: Reduced verification**

Run, from `web/app`: `npm run build` and `npx vitest run tests/unit/LiveStream.test.tsx`. Skip `npm run lint` and `npx playwright test` for this pass (per the process notes).

- [ ] **Step 8: Do not commit.** Report back per the process notes above.
