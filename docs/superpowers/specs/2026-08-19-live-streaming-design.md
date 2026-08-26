# Live LLM Response Streaming — Design Spec

## Goal

Show each agent's response typing out live on the research page while a
run is in progress, instead of only seeing results once the run
completes. This is the second deferred item from the design-integration
plan's scoped-out list (live per-agent status), extended to full
token-level streaming per the user's explicit request.

## Background / current architecture

- `api/worker.py` runs as a **separate process** from the API, on
  purpose (its own docstring: "The API must answer in milliseconds; an
  analysis takes 220-800 seconds. Those cannot share a process.").
- `execute_run()` calls `run_analysis()` via `asyncio.to_thread(...)` —
  a single blocking call that only returns once the ENTIRE multi-agent
  graph has finished (`TradingAgentsGraph.propagate()` →
  `self.graph.invoke(...)`).
- Nothing is visible to a client between "queued" and "completed" except
  a static status banner — the client polls `GET /runs/{id}` and gets
  `null` reports until the whole run is done.
- **The engine already proves streaming is possible.** `_run_graph()`
  (`tradingagents/graph/trading_graph.py:507`) has a `self.debug` branch
  that already calls `self.graph.stream(init_agent_state, **args)` —
  LangGraph's native per-node streaming — used today for developer debug
  output only, never wired to the API. `get_graph_args()`
  (`tradingagents/graph/propagation.py:91`) currently sets
  `stream_mode: "values"` (whole-state-after-each-node), not
  `"messages"` (token-level). LangGraph 1.2.11 is installed (confirmed:
  `pip show langgraph`), which fully supports `stream_mode="messages"`
  and multi-mode streaming (`stream_mode=["values", "messages"]`).

## Decision (architectural, made without a pause per explicit instruction)

**Transport: Server-Sent Events (SSE), not WebSockets.** One-directional
(server → browser), works over plain HTTP, needs no new library on
either side (`EventSource` is a browser built-in; FastAPI's
`StreamingResponse` is already a dependency), and — critically — SSE has
a native resume mechanism (`Last-Event-ID`) that fits this app's existing
durable run-id / leave-and-return design far better than a WebSocket
would.

**Cross-process relay: a new DB table (`run_events`), not Redis or an
in-process queue.** The worker and API are separate processes by
design (see above) and this prototype has zero external services
(explicit, repeated project philosophy — `api/worker.py`'s own docstring:
"Polling the database rather than subscribing to Redis keeps the
prototype at zero external services"). A `run_events` table, written by
the worker as tokens arrive and read by the API's SSE handler via the
same WAL-mode SQLite connection pattern `api/db.py` already documents
("WAL lets the API keep reading while a worker writes"), is the only
option consistent with everything this codebase already says about
itself. No new infrastructure.

**Worker-side write path: a plain synchronous `sqlite3` connection, not
the async SQLAlchemy engine.** `execute_run()` calls `run_analysis()`
via `asyncio.to_thread(...)` — the engine call runs in a plain thread,
outside the event loop. A streaming callback fired from inside that
thread (see below) writing through the async engine would require
awkward cross-loop scheduling for no benefit; a dedicated, short-lived
`sqlite3` connection opened once per run, written to synchronously and
debounced, is simpler and matches the "worker/API split" spirit (the
worker doesn't need the async stack it exists specifically to avoid
blocking).

**Debounced batching, not one row per token.** A single LLM response
across a multi-minute run can be hundreds of small token chunks.
Writing one DB row per token would thrash SQLite's single-writer
constraint (already a documented known limit — `api/db.py`: "SQLite
serialises writers. That is fine for a prototype... and NOT fine for
production concurrency"). Buffer chunks per node in memory and flush on
a small time/size threshold (250ms or 200 characters, whichever first).

**Retention: `run_events` rows are ephemeral, deleted once a run
completes or fails.** The full markdown reports (`Reports`) are the
permanent record — the token-by-token trace exists only to animate the
live view, has no value once the run is done, and keeping it around
forever grows the DB for no reason. Deleted in the same transaction that
marks the run completed/failed.

## Architecture

### 1. Engine — `tradingagents/graph/trading_graph.py`

New method, **not a change to the existing `propagate()`/`_run_graph()`
path** (that stays exactly as-is — this plan does not touch the
production non-streaming call path at all, same "don't touch tuned,
working code" discipline as the debate-ledger plan kept toward
`bull_researcher.py`/`bear_researcher.py`):

```python
def propagate_streaming(self, company_name, trade_date, asset_type="stock", on_token=None):
    """Like propagate(), but calls on_token(node_name, delta) as each
    LLM token arrives, in addition to returning the final state exactly
    as propagate() does. on_token is optional -- None means "run exactly
    like propagate(), no callback overhead."""
```

Internally: same setup as `_run_graph()` (ticker resolution, snapshot
date, memory-log resolution, checkpointer), then:

```python
final_state = {}
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
            on_token(node_name, delta)
```

`on_token` never raises to the caller's control flow — wrap the callback
invocation in `try/except Exception: logger.warning(...)` so a
downstream write failure (DB locked, disk full) degrades to "no live
view for this chunk," never fails the run.

### 2. DB — `api/db.py`

New table:

```python
class RunEvent(Base):
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

Same migration mechanism the debate-ledger plan already introduced —
`create_tables()` already runs `Base.metadata.create_all` (which
creates this whole new TABLE for free, no ALTER TABLE needed since it's
a brand-new table, not a new column on an existing one).

### 3. Worker-side write path — new module `api/streaming.py`

```python
class RunEventWriter:
    """Buffers streamed tokens and flushes them to run_events via a
    plain sync sqlite3 connection -- deliberately not the async engine
    (see spec: this runs inside execute_run's asyncio.to_thread, off
    the event loop)."""

    def __init__(self, db_path: str, run_id: str, flush_interval_s=0.25, flush_chars=200):
        ...

    def on_token(self, node_name: str, delta: str) -> None:
        """Buffer; flush when this node's buffer crosses flush_chars or
        flush_interval_s has elapsed since its last flush."""

    def flush_all(self) -> None:
        """Force-flush every buffered node. Called once at the end of a
        run (success or failure) so the last partial chunk isn't lost."""

    def close(self) -> None:
        ...
```

`api/worker.py::execute_run()` constructs one `RunEventWriter` per run,
passes `writer.on_token` as `propagate_streaming`'s `on_token`, calls
`writer.flush_all()` + `writer.close()` in a `finally` block regardless
of success/failure, and — after `mark_completed`/`mark_failed` — deletes
that run's `run_events` rows (via the store, see below).

### 4. Store — `api/store.py`

- `mark_completed`/`mark_failed` both, at the end, `DELETE FROM
  run_events WHERE run_id = :run_id` in the same transaction (ephemeral
  retention, per the Decision section).
- New read method: `get_events_since(run_id, after_seq) ->
  list[RunEventOut]`, ordered by `seq`, used by the SSE endpoint.

### 5. API — new endpoint `GET /runs/{run_id}/stream`

`api/routers/runs.py`, using FastAPI's `StreamingResponse` with
`media_type="text/event-stream"`:

```python
@router.get("/runs/{run_id}/stream", tags=["runs"])
async def stream_run(run_id: str, store: RunStoreDep, request: Request):
    async def event_source():
        last_seq = 0
        while True:
            if await request.is_disconnected():
                return
            run = await store.get(run_id)
            if run is None:
                return
            events = await store.get_events_since(run_id, last_seq)
            for event in events:
                last_seq = event.seq
                yield f"id: {event.seq}\ndata: {event.model_dump_json()}\n\n"
            if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(event_source(), media_type="text/event-stream")
```

Honors `Last-Event-ID` (a reconnecting `EventSource` sends it
automatically as a request header) so a browser refresh mid-run resumes
from where it left off rather than replaying from the start.

### 6. Frontend — new hook + component

- `web/app/src/lib/useRunStream.ts` — wraps `EventSource`, exposes
  `{ eventsByNode: Record<string, string> }` (accumulated text per
  node), auto-closes on the `done` event or on run completion (detected
  via the existing poll).
- New component, mounted ONLY while `status !== 'completed'` (replacing
  the static "running" banner's inert state with a live view): shows
  which node is currently active and its text accumulating in place,
  matching the CLI's own "Streaming Reasoning Log" concept
  (`assets/cli/cli_transaction.png`) ported to the web.
- Once status flips to `completed`, the stream closes and the existing
  `RunView`/`ReportsRecord`/`SourcesPanel`/`DebateLedger` rendering path
  takes over completely unchanged — this plan does not touch any of the
  completed-run rendering components.

## Data flow

```
worker: execute_run()
  -> RunEventWriter(db_path, run_id)
  -> asyncio.to_thread(run_analysis, ..., on_token=writer.on_token)
       -> TradingAgentsGraph.propagate_streaming(..., on_token=writer.on_token)
            -> self.graph.stream(..., stream_mode=["values","messages"])
                 -> on_token(node_name, delta) per LLM token
                      -> writer buffers, flushes to run_events (sync sqlite3)
       -> returns (verdict, reports, debate_ledger) exactly as today
  -> writer.flush_all() + writer.close() (finally block)
  -> store.mark_completed(...) -> deletes this run's run_events rows

api: GET /runs/{id}/stream
  -> polls run_events for rows after last_seq (WAL-mode concurrent read)
  -> forwards as SSE frames
  -> closes when run status is completed/failed

browser: useRunStream(runId)
  -> EventSource subscribes while status !== 'completed'
  -> live component renders accumulating text per node
  -> stream closes on 'done' event; existing completed-run UI takes over
```

## Error handling

- `on_token` never raises into the engine's control flow — a DB write
  failure degrades to "this chunk didn't make it to the live view,"
  never fails the run itself.
- If the SSE connection drops, the browser's native `EventSource`
  reconnect (with `Last-Event-ID`) picks up where it left off; no
  custom reconnect logic needed on the frontend.
- A run that fails: `run_events` rows are still deleted (in
  `mark_failed`, same as `mark_completed`) — the failure banner already
  shows the error, there's nothing left for a stale partial token trace
  to add.
- If a client never opens `/runs/{id}/stream` at all (e.g. the polling
  UI still works standalone), nothing about the existing flow changes —
  this is purely additive.

## Testing

- `propagate_streaming`: cannot be tested against a real LLM cheaply;
  test the callback wiring against a stubbed/fake compiled graph (the
  existing test suite already has a pattern for this — check
  `tests/test_ticker_identity_consistency.py::_graph_with_stubs()` for
  precedent on stubbing `TradingAgentsGraph` without a real provider
  call) asserting `on_token` fires with the right `(node_name, delta)`
  shape and that the final returned state matches what `propagate()`
  would have returned for the same stubbed run.
- `RunEventWriter`: unit tests for buffering/flush-threshold behavior
  against a temp sqlite file, no mocking of sqlite3 itself.
- `store.get_events_since`/deletion-on-completion: wiring tests
  following the `store`/`_run()` fixture convention already established
  in `tests/test_api_worker.py` and reused by the debate-ledger plan.
- SSE endpoint: a light integration test asserting the response's
  `media_type` and that events stop after a run is marked completed
  (using `httpx`'s streaming test client, or FastAPI's `TestClient` with
  a short polling-interval override for the test).
- Frontend: `useRunStream` hook test with a mocked `EventSource`; a
  render test for the live-view component's per-node accumulation.
- No changes needed to any existing completed-run test (E2E specs,
  `ReportsRecord`/`SourcesPanel`/`DebateLedger` tests) — this feature
  only touches the in-progress state.

## Non-goals

- No change to the non-streaming `propagate()`/`_run_graph()` path used
  by every existing test and the CLI's non-debug mode.
- No WebSocket, no Redis, no new external service.
- No historical playback of a completed run's token trace (ephemeral by
  design — see Decision section).
- No change to how `Verdict`/`Reports`/`DebateLedger` are computed or
  persisted — `run_analysis()`'s post-processing is unchanged, only its
  call to the engine gains an optional `on_token` passthrough.

## Global constraints for the implementation plan

- `propagate()`/`_run_graph()` (the existing, non-streaming path) must
  not be modified.
- `on_token` must never raise into the engine's execution — any failure
  in the callback degrades silently (logged, not propagated).
- `run_events` rows for a given run must be deleted once that run
  reaches `completed` or `failed` — never accumulate indefinitely.
- The worker-side writer uses a plain sync `sqlite3` connection, never
  the async SQLAlchemy engine (see Decision section for why).
- The SSE endpoint must honor `Last-Event-ID` for resume.
- Never add `Co-Authored-By: Claude` or any AI attribution to commits.
- Existing money-affecting contract rules (`Verdict`/`TradeLevels` null
  handling, 200 vs 202, rate-limit body) are unaffected.
