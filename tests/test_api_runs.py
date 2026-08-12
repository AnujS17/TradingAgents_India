"""HTTP surface for analysis runs.

The shape of these endpoints is forced by one fact: a run takes 220-800
seconds, so nothing here may block on the engine. POST queues and returns an
id; everything else reads state.
"""

import pytest
from fastapi.testclient import TestClient

from api.dependencies import InMemoryRunStore, get_run_store
from api.main import create_app
from api.schemas import RunStatus


@pytest.fixture
def client():
    app = create_app()
    # ONE store per test, shared across that test's requests. The lambda must
    # close over a single instance — returning InMemoryRunStore() from the
    # override builds a fresh store on every request, so nothing persists and
    # every cache lookup misses.
    store = InMemoryRunStore()
    app.dependency_overrides[get_run_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
def test_health_reports_unconfigured_dependencies(client):
    """Must be inspectable before Postgres and Redis exist, not 500."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "not_configured"
    assert body["queue"] == "not_configured"


@pytest.mark.unit
def test_analyze_queues_a_run_and_returns_a_poll_url(client):
    response = client.post("/analyze", json={"ticker": "SIEMENS.NS"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == RunStatus.QUEUED.value
    assert body["poll_url"] == f"/runs/{body['id']}"
    assert body["estimated_seconds"] > 0


@pytest.mark.unit
def test_repeat_request_reuses_the_existing_run(client):
    """The run cache is what makes on-demand analysis affordable for a public
    audience — and what stops two users getting two different verdicts for the
    same question. 202 means a run was spent; 200 means it was not."""
    first = client.post("/analyze", json={"ticker": "SIEMENS.NS"})
    second = client.post("/analyze", json={"ticker": "SIEMENS.NS"})

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["estimated_seconds"] == 0


@pytest.mark.unit
def test_ticker_is_normalised_before_the_cache_lookup(client):
    """'reliance ' and 'RELIANCE' must not each pay for a run."""
    first = client.post("/analyze", json={"ticker": "reliance "})
    second = client.post("/analyze", json={"ticker": "RELIANCE"})

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


@pytest.mark.unit
def test_different_profiles_are_different_runs(client):
    """fast and detailed produce materially different analyses, so one must
    not be served from the other's cache entry."""
    fast = client.post("/analyze", json={"ticker": "TCS.NS", "profile": "fast"})
    detailed = client.post("/analyze", json={"ticker": "TCS.NS", "profile": "detailed"})

    assert fast.status_code == 202
    assert detailed.status_code == 202
    assert fast.json()["id"] != detailed.json()["id"]


@pytest.mark.unit
def test_different_dates_are_different_runs(client):
    a = client.post("/analyze", json={"ticker": "TCS.NS", "analysis_date": "2026-08-11"})
    b = client.post("/analyze", json={"ticker": "TCS.NS", "analysis_date": "2026-08-12"})

    assert a.json()["id"] != b.json()["id"]


@pytest.mark.unit
def test_get_run_returns_the_queued_run(client):
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    response = client.get(f"/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == run_id
    assert body["ticker"] == "SIEMENS.NS"
    # No reports until the worker finishes.
    assert body["reports"] is None
    assert body["verdict"] is None


@pytest.mark.unit
def test_unknown_run_is_404(client):
    assert client.get("/runs/does-not-exist").status_code == 404


@pytest.mark.unit
def test_lookup_by_ticker_and_date(client):
    """The endpoint a stock page actually uses — it knows the company and the
    day, not a job id."""
    client.post("/analyze", json={"ticker": "SIEMENS.NS", "analysis_date": "2026-08-12"})

    response = client.get("/runs/SIEMENS.NS/2026-08-12")

    assert response.status_code == 200
    assert response.json()["cached"] is True


@pytest.mark.unit
def test_lookup_by_ticker_when_never_analysed_is_404_with_guidance(client):
    response = client.get("/runs/NOTHING.NS/2026-08-12")

    assert response.status_code == 404
    assert "POST /analyze" in response.json()["detail"]


@pytest.mark.unit
def test_blank_ticker_is_rejected(client):
    assert client.post("/analyze", json={"ticker": "   "}).status_code == 422


@pytest.mark.unit
def test_list_runs_is_newest_first_and_filterable(client):
    client.post("/analyze", json={"ticker": "AAA.NS"})
    client.post("/analyze", json={"ticker": "BBB.NS"})

    everything = client.get("/runs").json()
    assert [r["ticker"] for r in everything] == ["BBB.NS", "AAA.NS"]

    filtered = client.get("/runs", params={"ticker": "aaa.ns"}).json()
    assert [r["ticker"] for r in filtered] == ["AAA.NS"]


@pytest.mark.unit
def test_failed_runs_do_not_satisfy_the_cache():
    """One transient vendor outage must not poison a ticker for the rest of
    the day by making every later request return the failure.

    Driven through asyncio.run rather than an async test so the suite needs no
    async plugin — the store is the only async surface here.
    """
    import asyncio
    from datetime import date

    from api.schemas import AnalysisProfile

    async def scenario():
        store = InMemoryRunStore()
        run = await store.create("SIEMENS.NS", date(2026, 8, 12), AnalysisProfile.FAST)
        store._runs[run.id] = run.model_copy(update={"status": RunStatus.FAILED})
        return await store.find("SIEMENS.NS", date(2026, 8, 12), AnalysisProfile.FAST)

    assert asyncio.run(scenario()) is None


# --- forced fresh analysis -------------------------------------------------
#
# A user viewing a cached analysis can request a fresh one. Runs ACCUMULATE
# rather than overwrite, because the comparison is the point: the day's inputs
# are snapshotted, so two runs read identical data and a difference means the
# evidence is genuinely balanced.


@pytest.mark.unit
def test_force_queues_a_new_run_even_when_one_exists(client):
    first = client.post("/analyze", json={"ticker": "SIEMENS.NS"})
    forced = client.post("/analyze", json={"ticker": "SIEMENS.NS", "force": True})

    assert first.status_code == 202
    assert forced.status_code == 202, "force must spend a run, not serve cache"
    assert forced.json()["id"] != first.json()["id"]
    assert forced.json()["estimated_seconds"] > 0


@pytest.mark.unit
def test_forcing_does_not_destroy_the_earlier_run(client):
    """The user still needs the analysis they were already reading."""
    first_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    client.post("/analyze", json={"ticker": "SIEMENS.NS", "force": True})

    assert client.get(f"/runs/{first_id}").status_code == 200


@pytest.mark.unit
def test_run_count_reflects_repeat_analyses(client):
    client.post("/analyze", json={"ticker": "SIEMENS.NS"})
    client.post("/analyze", json={"ticker": "SIEMENS.NS", "force": True})
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS", "force": True}).json()["id"]

    assert client.get(f"/runs/{run_id}").json()["run_count"] == 3


@pytest.mark.unit
def test_refresh_data_implies_force(client):
    """Re-fetching without re-running would throw the new data away."""
    client.post("/analyze", json={"ticker": "SIEMENS.NS"})
    second = client.post("/analyze", json={"ticker": "SIEMENS.NS", "refresh_data": True})

    assert second.status_code == 202


@pytest.mark.unit
def test_history_lists_every_run_newest_first(client):
    client.post("/analyze", json={"ticker": "SIEMENS.NS", "analysis_date": "2026-08-12"})
    latest = client.post(
        "/analyze",
        json={"ticker": "SIEMENS.NS", "analysis_date": "2026-08-12", "force": True},
    ).json()["id"]

    body = client.get("/runs/SIEMENS.NS/2026-08-12/history").json()

    assert body["run_count"] == 2
    assert body["runs"][0]["id"] == latest


@pytest.mark.unit
def test_history_is_404_when_nothing_was_ever_run(client):
    assert client.get("/runs/NOTHING.NS/2026-08-12/history").status_code == 404


@pytest.mark.unit
def test_disagreeing_repeat_runs_are_flagged_as_contested():
    """The honest case. Two runs of the SAME question with the SAME snapshotted
    data reached different ratings — observed live on SIEMENS.NS (Hold vs
    Sell/Underweight). Surface it rather than silently showing whichever ran
    last.
    """
    import asyncio
    from datetime import date

    from api.schemas import AnalysisProfile, Verdict

    async def scenario():
        store = InMemoryRunStore()
        day = date(2026, 8, 12)
        a = await store.create("SIEMENS.NS", day, AnalysisProfile.FAST)
        b = await store.create("SIEMENS.NS", day, AnalysisProfile.FAST)
        store._runs[a.id] = a.model_copy(
            update={"status": RunStatus.COMPLETED, "verdict": Verdict(rating="Hold")}
        )
        store._runs[b.id] = b.model_copy(
            update={"status": RunStatus.COMPLETED, "verdict": Verdict(rating="Underweight")}
        )
        return await store.history("SIEMENS.NS", day, AnalysisProfile.FAST)

    history = asyncio.run(scenario())
    assert history.verdict_is_contested is True
    assert set(history.ratings) == {"Hold", "Underweight"}


@pytest.mark.unit
def test_agreeing_repeat_runs_are_not_flagged():
    """Repeat runs that agree must NOT be marked contested — otherwise the
    flag means nothing."""
    import asyncio
    from datetime import date

    from api.schemas import AnalysisProfile, Verdict

    async def scenario():
        store = InMemoryRunStore()
        day = date(2026, 8, 12)
        for _ in range(2):
            run = await store.create("TCS.NS", day, AnalysisProfile.FAST)
            store._runs[run.id] = run.model_copy(
                update={"status": RunStatus.COMPLETED, "verdict": Verdict(rating="Hold")}
            )
        return await store.history("TCS.NS", day, AnalysisProfile.FAST)

    assert asyncio.run(scenario()).verdict_is_contested is False


@pytest.mark.unit
def test_find_prefers_a_completed_run_over_one_still_executing():
    """Someone asking the question wants an answer now; the in-flight run
    surfaces on its own once done."""
    import asyncio
    from datetime import date

    from api.schemas import AnalysisProfile, Verdict

    async def scenario():
        store = InMemoryRunStore()
        day = date(2026, 8, 12)
        done = await store.create("TCS.NS", day, AnalysisProfile.FAST)
        store._runs[done.id] = done.model_copy(
            update={"status": RunStatus.COMPLETED, "verdict": Verdict(rating="Hold")}
        )
        await store.create("TCS.NS", day, AnalysisProfile.FAST)  # newer, still queued
        return await store.find("TCS.NS", day, AnalysisProfile.FAST), done.id

    found, done_id = asyncio.run(scenario())
    assert found.id == done_id
    assert found.status is RunStatus.COMPLETED
