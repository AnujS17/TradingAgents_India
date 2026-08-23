"""The kitchen: database-backed queue, worker execution, and spend limits.

The engine itself is stubbed throughout — these tests are about the plumbing
(does a queued run get claimed, executed, and written back?), not about the
analysis. A real run takes 220-800 seconds and costs money.
"""

import asyncio
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import Base
from api.schemas import AnalysisProfile, Reports, RunStatus, Verdict
from api.store import SqlRunStore

DAY = date(2026, 8, 12)


@pytest.fixture
def store(tmp_path):
    """A real SQLite database per test, on disk.

    On disk rather than :memory: because each connection in the pool would get
    its OWN empty in-memory database, so a write on one connection is invisible
    to the next read — exactly the bug this suite exists to catch.
    """
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
def test_a_queued_run_can_be_claimed(store):
    async def scenario():
        created = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        claimed = await store.claim_next_run()
        return created.id, claimed

    created_id, claimed = _run(scenario())
    assert claimed is not None
    assert claimed.id == created_id
    assert claimed.status == RunStatus.RUNNING.value


@pytest.mark.unit
def test_a_claimed_run_is_not_handed_out_twice(store):
    """Two workers must never run the same job — a duplicate costs a full
    analysis. The claim UPDATE is conditional on the row still being queued,
    so exactly one worker wins."""

    async def scenario():
        await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        first = await store.claim_next_run()
        second = await store.claim_next_run()
        return first, second

    first, second = _run(scenario())
    assert first is not None
    assert second is None


@pytest.mark.unit
def test_claims_are_oldest_first(store):
    async def scenario():
        older = await store.create("AAA.NS", DAY, AnalysisProfile.FAST)
        await store.create("BBB.NS", DAY, AnalysisProfile.FAST)
        claimed = await store.claim_next_run()
        return older.id, claimed.id

    older_id, claimed_id = _run(scenario())
    assert claimed_id == older_id


@pytest.mark.unit
def test_worker_executes_a_run_and_stores_the_result(store, monkeypatch):
    """The whole point: a queued run comes back completed, with reports."""
    import api.service

    monkeypatch.setattr(
        api.service,
        "run_analysis",
        lambda ticker, day, profile, refresh, *a, **k: (
            Verdict(rating="Underweight", price_target=3200.0),
            Reports(final_decision="Reduce into strength."),
        ),
    )

    async def scenario():
        from api.worker import worker_loop

        created = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        stop = asyncio.Event()
        task = asyncio.create_task(worker_loop(stop, store=store))
        # Poll until the worker finishes rather than sleeping a fixed amount,
        # so this neither flakes on a slow machine nor wastes time on a fast one.
        for _ in range(100):
            await asyncio.sleep(0.05)
            current = await store.get(created.id)
            if current.status is RunStatus.COMPLETED:
                break
        stop.set()
        await task
        return await store.get(created.id)

    result = _run(scenario())
    assert result.status is RunStatus.COMPLETED
    assert result.verdict.rating == "Underweight"
    assert result.verdict.price_target == 3200.0
    assert result.reports.final_decision == "Reduce into strength."
    assert result.completed_at is not None


@pytest.mark.unit
def test_an_engine_crash_marks_the_run_failed_instead_of_killing_the_worker(
    store, monkeypatch
):
    """An uncaught exception would leave the run stuck in 'running' forever
    while the user polls an answer that never arrives."""
    import api.service

    def boom(*_args, **_kwargs):
        raise RuntimeError("vendor exploded")

    monkeypatch.setattr(api.service, "run_analysis", boom)

    async def scenario():
        from api.worker import execute_run

        created = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        claimed = await store.claim_next_run()
        await execute_run(store, claimed)
        return await store.get(created.id)

    result = _run(scenario())
    assert result.status is RunStatus.FAILED
    assert "vendor exploded" in result.error


@pytest.mark.unit
def test_a_failed_run_does_not_satisfy_the_cache(store, monkeypatch):
    """One vendor outage must not poison that ticker for the rest of the day."""
    import api.service

    monkeypatch.setattr(
        api.service, "run_analysis", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    )

    async def scenario():
        from api.worker import execute_run

        await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        claimed = await store.claim_next_run()
        await execute_run(store, claimed)
        return await store.find("SIEMENS.NS", DAY, AnalysisProfile.FAST)

    assert _run(scenario()) is None


@pytest.mark.unit
def test_results_survive_a_new_store_instance(store, monkeypatch):
    """Persistence, which the in-memory store could not provide: a restarted
    API must still see what a worker wrote."""
    import api.service

    monkeypatch.setattr(
        api.service,
        "run_analysis",
        lambda *a, **k: (Verdict(rating="Hold"), Reports(final_decision="Sit tight.")),
    )

    async def scenario():
        from api.worker import execute_run

        created = await store.create("TCS.NS", DAY, AnalysisProfile.FAST)
        claimed = await store.claim_next_run()
        await execute_run(store, claimed)
        # A different store object over the same database stands in for a
        # separate process.
        fresh = SqlRunStore(sessionmaker=store._sessionmaker)
        return await fresh.get(created.id)

    result = _run(scenario())
    assert result.status is RunStatus.COMPLETED
    assert result.verdict.rating == "Hold"


@pytest.mark.unit
def test_refresh_data_reaches_the_worker(store, monkeypatch):
    """The flag has to survive the hand-off through the queue, or forcing a
    data refresh silently replays the old snapshot."""
    import api.service

    seen = {}
    monkeypatch.setattr(
        api.service,
        "run_analysis",
        lambda ticker, day, profile, refresh, *a, **k: (
            seen.update(refresh=refresh),
            (Verdict(), Reports()),
        )[1],
    )

    async def scenario():
        from api.worker import execute_run

        await store.create("TCS.NS", DAY, AnalysisProfile.FAST, refresh_data=True)
        claimed = await store.claim_next_run()
        await execute_run(store, claimed)

    _run(scenario())
    assert seen["refresh"] is True


@pytest.mark.unit
def test_requested_time_horizon_reaches_the_worker(store, monkeypatch):
    """Same hand-off-through-the-queue guard as refresh_data, for the
    optional holding-period parameter."""
    import api.service

    seen = {}
    monkeypatch.setattr(
        api.service,
        "run_analysis",
        lambda ticker, day, profile, refresh, on_token, should_stop, horizon=None: (
            seen.update(horizon=horizon),
            (Verdict(), Reports()),
        )[1],
    )

    async def scenario():
        from api.worker import execute_run

        await store.create("TCS.NS", DAY, AnalysisProfile.FAST, time_horizon="3-6 months")
        claimed = await store.claim_next_run()
        await execute_run(store, claimed)

    _run(scenario())
    assert seen["horizon"] == "3-6 months"


@pytest.mark.unit
def test_history_returns_correct_run_summaries(store, monkeypatch):
    """Fix regression guard: history() validates RunSummary directly from the
    ORM row instead of building a full RunDetail (via _to_detail, which runs
    the news-sources parser) purely to downcast it — RunSummary has no
    news_sources field, so that work was wasted. Confirms the lightweight
    path still yields correct fields."""
    import api.service

    monkeypatch.setattr(
        api.service,
        "run_analysis",
        lambda *a, **k: (Verdict(rating="Buy"), Reports(final_decision="Accumulate.")),
    )

    async def scenario():
        from api.worker import execute_run

        await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        claimed = await store.claim_next_run()
        await execute_run(store, claimed)
        return await store.history("SIEMENS.NS", DAY, AnalysisProfile.FAST)

    history = _run(scenario())
    assert history.run_count == 1
    assert len(history.runs) == 1
    summary = history.runs[0]
    assert summary.ticker == "SIEMENS.NS"
    assert summary.analysis_date == DAY
    assert summary.profile is AnalysisProfile.FAST
    assert summary.status is RunStatus.COMPLETED
    assert summary.completed_at is not None


@pytest.mark.unit
def test_list_returns_correct_run_summaries(store, monkeypatch):
    """Same guard as test_history_returns_correct_run_summaries, for the
    other endpoint (`list()`) that was also going through _to_detail()
    needlessly."""
    import api.service

    monkeypatch.setattr(
        api.service,
        "run_analysis",
        lambda *a, **k: (Verdict(rating="Sell"), Reports(final_decision="Trim.")),
    )

    async def scenario():
        from api.worker import execute_run

        await store.create("TCS.NS", DAY, AnalysisProfile.FAST)
        claimed = await store.claim_next_run()
        await execute_run(store, claimed)
        return await store.list(ticker="TCS.NS", limit=10, offset=0)

    summaries = _run(scenario())
    assert len(summaries) == 1
    assert summaries[0].ticker == "TCS.NS"
    assert summaries[0].status is RunStatus.COMPLETED


@pytest.mark.unit
def test_run_counter_is_per_client_and_global(store):
    async def scenario():
        await store.create("A.NS", DAY, AnalysisProfile.FAST, requested_by="1.1.1.1")
        await store.create("B.NS", DAY, AnalysisProfile.FAST, requested_by="1.1.1.1")
        await store.create("C.NS", DAY, AnalysisProfile.FAST, requested_by="2.2.2.2")
        return (
            await store.count_runs_today(),
            await store.count_runs_today(requested_by="1.1.1.1"),
        )

    total, mine = _run(scenario())
    assert total == 3
    assert mine == 2
