"""HTTP-layer ownership: a user must never be able to read, stream,
export, stop, resume, or subscribe to another user's run. 404, not 403 --
confirming existence to a non-owner leaks which tickers others research."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from api.auth import get_current_user
from api.dependencies import InMemoryRunStore, get_run_store
from api.main import create_app
from api.schemas import RunStatus


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client_and_store():
    app = create_app()
    store = InMemoryRunStore()
    app.dependency_overrides[get_run_store] = lambda: store
    with TestClient(app) as test_client:
        yield app, test_client, store


def _as_user(app, user_id: str, role: str = "user"):
    from api.auth import CurrentUser

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=user_id, role=role, tier="free")


@pytest.mark.unit
def test_get_run_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    _as_user(app, "user-b")
    resp = client.get(f"/runs/{run_id}")

    assert resp.status_code == 404


@pytest.mark.unit
def test_get_run_succeeds_for_the_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    resp = client.get(f"/runs/{run_id}")

    assert resp.status_code == 200


@pytest.mark.unit
def test_get_run_succeeds_for_an_admin_who_is_not_the_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    _as_user(app, "admin-1", role="admin")
    resp = client.get(f"/runs/{run_id}")

    assert resp.status_code == 200


@pytest.mark.unit
def test_stop_run_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    _as_user(app, "user-b")
    resp = client.post(f"/runs/{run_id}/stop")

    assert resp.status_code == 404


@pytest.mark.unit
def test_list_runs_only_returns_the_callers_own(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    client.post("/analyze", json={"ticker": "SIEMENS.NS"})
    _as_user(app, "user-b")
    client.post("/analyze", json={"ticker": "HAL.NS"})

    resp = client.get("/runs")

    tickers = {r["ticker"] for r in resp.json()}
    assert tickers == {"HAL.NS"}


@pytest.mark.unit
def test_list_runs_returns_everything_for_an_admin(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    client.post("/analyze", json={"ticker": "SIEMENS.NS"})
    _as_user(app, "admin-1", role="admin")
    client.post("/analyze", json={"ticker": "HAL.NS"})

    resp = client.get("/runs")

    tickers = {r["ticker"] for r in resp.json()}
    assert tickers == {"SIEMENS.NS", "HAL.NS"}


def _completed_run(store, run_id: str) -> None:
    """Mirrors tests/test_export.py's `_complete` helper -- export needs a
    real verdict/reports to build a real PDF/workbook from."""
    from api.schemas import Reports, TradeLevels, Verdict

    store._runs[run_id] = store._runs[run_id].model_copy(
        update={
            "status": RunStatus.COMPLETED,
            "verdict": Verdict(rating="Buy", levels=TradeLevels(action="Buy")),
            "reports": Reports(final_decision="**Rating**: Buy"),
        }
    )


@pytest.mark.unit
def test_resume_run_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    store._runs[run_id] = store._runs[run_id].model_copy(update={"status": RunStatus.FAILED})

    _as_user(app, "user-b")
    resp = client.post(f"/runs/{run_id}/resume")

    assert resp.status_code == 404


@pytest.mark.unit
def test_resume_run_succeeds_for_the_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    store._runs[run_id] = store._runs[run_id].model_copy(update={"status": RunStatus.FAILED})

    resp = client.post(f"/runs/{run_id}/resume")

    assert resp.status_code == 202


@pytest.mark.unit
def test_subscribe_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    _as_user(app, "user-b")
    resp = client.post(
        f"/runs/{run_id}/subscribe",
        json={"endpoint": "https://push.example/x", "keys": {"p256dh": "p", "auth": "a"}},
    )

    assert resp.status_code == 404


@pytest.mark.unit
def test_subscribe_succeeds_for_the_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    resp = client.post(
        f"/runs/{run_id}/subscribe",
        json={"endpoint": "https://push.example/x", "keys": {"p256dh": "p", "auth": "a"}},
    )

    assert resp.status_code == 204


@pytest.mark.unit
def test_stream_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    _as_user(app, "user-b")
    resp = client.get(f"/runs/{run_id}/stream", headers={"Accept": "text/event-stream"})

    assert resp.status_code == 404


@pytest.mark.unit
def test_export_pdf_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    _completed_run(store, run_id)

    _as_user(app, "user-b")
    resp = client.get(f"/runs/{run_id}/export.pdf")

    assert resp.status_code == 404


@pytest.mark.unit
def test_export_pdf_succeeds_for_the_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    _completed_run(store, run_id)

    resp = client.get(f"/runs/{run_id}/export.pdf")

    assert resp.status_code == 200


@pytest.mark.unit
def test_export_excel_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    _completed_run(store, run_id)

    _as_user(app, "user-b")
    resp = client.get(f"/runs/{run_id}/export.xlsx")

    assert resp.status_code == 404


@pytest.mark.unit
def test_export_excel_succeeds_for_the_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    _completed_run(store, run_id)

    resp = client.get(f"/runs/{run_id}/export.xlsx")

    assert resp.status_code == 200


@pytest.mark.unit
def test_admin_can_look_up_another_users_run_by_ticker_and_date(client_and_store):
    """Regression test for the admin-bypass gap: owner=None alone must never
    mean 'no filter' for find/history (that would leak an unclaimed-only
    view), so the admin path uses bypass_owner_check=True instead. This
    fails against the old owner=None-for-admin code (404, since no unclaimed
    row exists) and passes against the fix."""
    app, client, store = client_and_store
    _as_user(app, "user-a")
    client.post(
        "/analyze", json={"ticker": "SIEMENS.NS", "analysis_date": "2026-08-20"}
    )

    _as_user(app, "admin-1", role="admin")
    resp = client.get("/runs/SIEMENS.NS/2026-08-20")

    assert resp.status_code == 200
    assert resp.json()["ticker"] == "SIEMENS.NS"
    assert resp.json()["user_id"] == "user-a"


@pytest.mark.unit
def test_admin_can_view_another_users_run_history(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    client.post(
        "/analyze", json={"ticker": "SIEMENS.NS", "analysis_date": "2026-08-20"}
    )

    _as_user(app, "admin-1", role="admin")
    resp = client.get("/runs/SIEMENS.NS/2026-08-20/history")

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_count"] == 1
    assert body["runs"][0]["ticker"] == "SIEMENS.NS"


@pytest.mark.unit
def test_get_run_by_ticker_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    client.post(
        "/analyze", json={"ticker": "SIEMENS.NS", "analysis_date": "2026-08-20"}
    )

    _as_user(app, "user-b")
    resp = client.get("/runs/SIEMENS.NS/2026-08-20")

    assert resp.status_code == 404


@pytest.mark.unit
def test_run_history_404s_for_a_non_owner(client_and_store):
    app, client, store = client_and_store
    _as_user(app, "user-a")
    client.post(
        "/analyze", json={"ticker": "SIEMENS.NS", "analysis_date": "2026-08-20"}
    )

    _as_user(app, "user-b")
    resp = client.get("/runs/SIEMENS.NS/2026-08-20/history")

    assert resp.status_code == 404


@pytest.mark.unit
def test_resumed_run_stays_owned_by_the_original_owner(client_and_store):
    """create_resume must propagate user_id from the failed run to the new
    one -- otherwise a resumed run would either be unclaimed (user_id=None)
    or, worse, silently reassigned to whoever happened to trigger the
    resume."""
    app, client, store = client_and_store
    _as_user(app, "user-a")
    run_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    store._runs[run_id] = store._runs[run_id].model_copy(update={"status": RunStatus.FAILED})

    resp = client.post(f"/runs/{run_id}/resume")
    new_run_id = resp.json()["id"]

    assert store._runs[new_run_id].user_id == "user-a"


@pytest.mark.unit
def test_analyze_without_a_token_is_rejected(client_and_store):
    app, client, store = client_and_store
    # No _as_user() override -- get_current_user runs for real and rejects.

    resp = client.post("/analyze", json={"ticker": "SIEMENS.NS"})

    assert resp.status_code == 401


@pytest.mark.unit
def test_health_needs_no_token(client_and_store):
    app, client, store = client_and_store

    resp = client.get("/health")

    assert resp.status_code == 200


@pytest.mark.unit
def test_vapid_key_needs_no_token(client_and_store):
    app, client, store = client_and_store

    resp = client.get("/push/vapid-public-key")

    assert resp.status_code == 200
