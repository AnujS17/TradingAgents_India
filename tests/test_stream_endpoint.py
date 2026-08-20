"""Guard for GET /runs/{run_id}/stream. Follows this project's existing
router-test convention: fastapi.testclient.TestClient against the real app,
with get_run_store overridden to a single InMemoryRunStore instance shared
across a test's requests (see tests/test_api_runs.py).
"""

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.dependencies import InMemoryRunStore, get_run_store
from api.main import create_app
from api.schemas import AnalysisProfile, RunStatus


@pytest.fixture
def store():
    return InMemoryRunStore()


@pytest.fixture
def client(store):
    app = create_app()
    # Same store instance backs every request in the test, exactly as in
    # tests/test_api_runs.py -- and here the test also holds a direct
    # reference to it, needed to force a run into "completed" without a
    # real engine run.
    app.dependency_overrides[get_run_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client


def _run(coro):
    return asyncio.run(coro)


def _create_completed_run(store: InMemoryRunStore) -> str:
    """Create a run directly against the store, then mark it completed by
    mutating the stored RunDetail in place. InMemoryRunStore has no
    mark_completed of its own (that lives on SqlRunStore), and the run must
    already be completed before the stream is opened -- otherwise the
    endpoint's poll loop never sees a terminal status and the test hangs."""
    created = _run(store.create("SIEMENS.NS", date(2026, 8, 1), AnalysisProfile.FAST))
    store._runs[created.id].status = RunStatus.COMPLETED
    return created.id


@pytest.mark.unit
def test_stream_endpoint_returns_event_stream_media_type(client, store):
    """The response Content-Type must be text/event-stream, or a browser
    EventSource will refuse to treat it as SSE."""
    run_id = _create_completed_run(store)

    response = client.get(
        f"/runs/{run_id}/stream", headers={"Accept": "text/event-stream"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.unit
def test_stream_closes_after_run_is_marked_completed(client, store):
    """A completed run's stream must terminate (send the 'done' event and
    end), not poll forever."""
    run_id = _create_completed_run(store)

    response = client.get(
        f"/runs/{run_id}/stream", headers={"Accept": "text/event-stream"}
    )

    assert response.status_code == 200
    assert "event: done" in response.text
