"""POST /runs/{id}/resume: continue a failed run instead of restarting it.

Covers the store layer (SqlRunStore.create_resume, InMemoryRunStore.
create_resume) and the HTTP layer (the router endpoint itself), following
the same patterns tests/test_api_worker.py and tests/test_api_runs.py
already use for each.
"""

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.auth import CurrentUser, get_current_user
from api.db import Base
from api.dependencies import InMemoryRunStore, get_run_store
from api.main import create_app
from api.schemas import AnalysisProfile, RunStatus
from api.store import SqlRunStore

DAY = date(2026, 8, 26)


@pytest.fixture
def sql_store(tmp_path):
    """Mirrors tests/test_api_worker.py's `store` fixture."""
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


# --- store layer -------------------------------------------------------


@pytest.mark.unit
def test_create_resume_returns_none_for_an_unknown_run(sql_store):
    result = _run(sql_store.create_resume("does-not-exist"))

    assert result is None


@pytest.mark.unit
def test_create_resume_returns_none_for_a_run_that_did_not_fail(sql_store):
    async def scenario():
        created = await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        return await sql_store.create_resume(created.id)  # still queued

    assert _run(scenario()) is None


@pytest.mark.unit
def test_create_resume_queues_a_new_run_carrying_over_the_original_settings(sql_store):
    """The new run must match the failed one's ticker/date/profile/
    refresh_data/time_horizon -- it's a continuation, not a fresh request
    with defaults. The failed row itself must be left untouched (still
    findable, still failed) so the run history stays an honest record."""

    async def scenario():
        created = await sql_store.create(
            "SIEMENS.NS",
            DAY,
            AnalysisProfile.DETAILED,
            refresh_data=True,
            time_horizon="3-6 months",
        )
        await sql_store.mark_failed(created.id, "ConnectionError: network dropped")

        resumed = await sql_store.create_resume(created.id, requested_by="1.2.3.4")
        original_after = await sql_store.get(created.id)
        return resumed, original_after

    resumed, original_after = _run(scenario())

    assert resumed is not None
    assert resumed.id != original_after.id
    assert resumed.status is RunStatus.QUEUED
    assert resumed.ticker == "SIEMENS.NS"
    assert resumed.analysis_date == DAY
    assert resumed.profile is AnalysisProfile.DETAILED
    assert resumed.requested_time_horizon == "3-6 months"

    assert original_after.status is RunStatus.FAILED
    assert original_after.error == "ConnectionError: network dropped"


@pytest.mark.unit
def test_in_memory_store_create_resume_matches_the_same_contract():
    """InMemoryRunStore backs the dev/test dependency override -- its
    create_resume must satisfy the same None-vs-queued contract as the real
    store, or a test written against it would pass for the wrong reasons."""

    async def scenario():
        store = InMemoryRunStore()
        created = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)

        not_yet_failed = await store.create_resume(created.id)

        store._runs[created.id] = created.model_copy(update={"status": RunStatus.FAILED})
        resumed = await store.create_resume(created.id)
        missing = await store.create_resume("does-not-exist")
        return not_yet_failed, resumed, missing

    not_yet_failed, resumed, missing = _run(scenario())

    assert not_yet_failed is None
    assert missing is None
    assert resumed is not None
    assert resumed.status is RunStatus.QUEUED
    assert resumed.ticker == "SIEMENS.NS"


# --- HTTP layer ----------------------------------------------------------


@pytest.fixture
def client_and_store():
    app = create_app()
    store = InMemoryRunStore()
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="test-user", role="user", tier="free"
    )
    with TestClient(app) as test_client:
        yield test_client, store


@pytest.mark.unit
def test_resume_endpoint_queues_a_new_run_for_a_failed_one(client_and_store):
    client, store = client_and_store
    created_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    store._runs[created_id] = store._runs[created_id].model_copy(
        update={"status": RunStatus.FAILED}
    )

    response = client.post(f"/runs/{created_id}/resume")

    assert response.status_code == 202
    body = response.json()
    assert body["id"] != created_id
    assert body["status"] == RunStatus.QUEUED.value
    assert body["poll_url"] == f"/runs/{body['id']}"


@pytest.mark.unit
def test_resume_endpoint_404s_for_an_unknown_run(client_and_store):
    client, _store = client_and_store

    response = client.post("/runs/does-not-exist/resume")

    assert response.status_code == 404


@pytest.mark.unit
def test_resume_endpoint_404s_for_a_run_that_has_not_failed(client_and_store):
    client, _store = client_and_store
    created_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    response = client.post(f"/runs/{created_id}/resume")  # still queued, never failed

    assert response.status_code == 404


# --- config + worker wiring ------------------------------------------------


@pytest.mark.unit
def test_build_config_enables_checkpointing_for_both_profiles():
    """Every API-driven run needs a checkpoint available to resume from --
    run_analysis's resume=False default is what keeps a normal run from
    ever seeing stale state, so turning this on globally is safe."""
    from api.service import build_config

    assert build_config(AnalysisProfile.FAST)["checkpoint_enabled"] is True
    assert build_config(AnalysisProfile.DETAILED)["checkpoint_enabled"] is True


@pytest.mark.unit
def test_run_analysis_forwards_resume_to_the_engine(monkeypatch):
    """resume has to actually reach propagate_streaming, not just exist as a
    parameter -- this is the wiring test for that one line."""
    import api.service as service

    seen = {}

    class _FakeGraph:
        def __init__(self, config):
            pass

        def propagate_streaming(self, ticker, date_str, **kwargs):
            seen.update(kwargs)
            return {}

    monkeypatch.setattr(
        "tradingagents.graph.trading_graph.TradingAgentsGraph", _FakeGraph
    )
    monkeypatch.setattr(
        service, "_extract_verdict", lambda state: None
    )
    monkeypatch.setattr(service, "_extract_reports", lambda state: None)

    service.run_analysis(
        "SIEMENS.NS",
        DAY,
        AnalysisProfile.FAST,
        on_token=lambda *_a: None,
        resume=True,
    )

    assert seen["resume"] is True


@pytest.mark.unit
def test_execute_run_forwards_the_row_resume_flag(sql_store, monkeypatch):
    """api.worker.execute_run must read row.resume, not silently default it
    -- a resumed run's whole point is lost if this is dropped on the floor
    between the queue row and the engine call."""
    import api.service
    from api.schemas import Reports, Verdict
    from api.worker import execute_run

    seen = {}

    def fake_run_analysis(ticker, day, profile, refresh, on_token, should_stop, horizon, resume=False):
        seen["resume"] = resume
        return Verdict(), Reports()

    monkeypatch.setattr(api.service, "run_analysis", fake_run_analysis)

    async def scenario():
        # create_resume always sets resume=True on the row it creates; go
        # through it (rather than poking the column directly) so this test
        # also guards that create_resume's own flag actually persists.
        original = await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        await sql_store.mark_failed(original.id, "boom")
        await sql_store.create_resume(original.id)

        claimed = await sql_store.claim_next_run()
        await execute_run(sql_store, claimed)

    _run(scenario())

    assert seen["resume"] is True
