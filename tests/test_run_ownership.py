"""HTTP-layer ownership: a user must never be able to read, stream,
export, stop, resume, or subscribe to another user's run. 404, not 403 --
confirming existence to a non-owner leaks which tickers others research."""

import asyncio

import jwt
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from api.auth import get_current_user
from api.db import Base, User
from api.dependencies import InMemoryRunStore, get_run_store
from api.main import create_app
from api.schemas import AnalysisProfile


def _run(coro):
    return asyncio.run(coro)


def _bearer(user_id: str, role: str = "user", tier: str = "free") -> dict:
    """Bypasses real JWT signing for these tests -- they override
    get_current_user directly, the same way other tests override
    get_run_store, so this file tests ownership logic, not token parsing
    (already covered by tests/test_auth.py)."""
    return {"id": user_id, "role": role, "tier": tier}


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
