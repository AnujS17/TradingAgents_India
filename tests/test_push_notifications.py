"""api.push: VAPID key persistence and best-effort send.

No real push service is contacted in these tests -- send() is exercised
either against a deliberately bogus endpoint (proving the network failure
is swallowed, not raised) or with pywebpush.webpush itself mocked out.
"""

import asyncio
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.push as push
from api.db import Base
from api.schemas import AnalysisProfile, RunStatus
from api.store import SqlRunStore

DAY = date(2026, 8, 27)


@pytest.fixture(autouse=True)
def _reset_cached_vapid():
    """api.push caches the loaded keypair at module scope; each test needs
    its own so tmp_path-based key files from other tests never leak in."""
    push._vapid = None
    yield
    push._vapid = None


@pytest.mark.unit
def test_get_vapid_generates_and_persists_a_keypair(tmp_path, monkeypatch):
    monkeypatch.setattr(push, "_keys_path", lambda: str(tmp_path / "vapid.pem"))

    vapid = push.get_vapid()

    assert (tmp_path / "vapid.pem").exists()
    assert vapid.public_key is not None
    assert vapid.private_key is not None


@pytest.mark.unit
def test_get_vapid_reuses_the_persisted_key_across_process_restarts(tmp_path, monkeypatch):
    """The whole point of persisting to disk: a subscription is bound to the
    public key it was created against, so a fresh key on every restart would
    silently break every previously-granted browser subscription."""
    monkeypatch.setattr(push, "_keys_path", lambda: str(tmp_path / "vapid.pem"))

    first_public_key = push.public_key_b64()

    # Simulate a fresh process: drop the in-memory cache, reload from disk.
    push._vapid = None
    second_public_key = push.public_key_b64()

    assert first_public_key == second_public_key


@pytest.mark.unit
def test_public_key_b64_is_url_safe_and_the_right_shape(tmp_path, monkeypatch):
    """PushManager.subscribe's applicationServerKey needs an uncompressed EC
    point: 65 raw bytes (0x04 prefix + 32-byte X + 32-byte Y), base64url
    encoded. Wrong shape here fails silently in the browser with no useful
    error, so this is worth pinning."""
    import base64

    monkeypatch.setattr(push, "_keys_path", lambda: str(tmp_path / "vapid.pem"))

    key = push.public_key_b64()

    assert "+" not in key and "/" not in key  # URL-safe alphabet only
    padded = key + "=" * (-len(key) % 4)
    raw = base64.urlsafe_b64decode(padded)
    assert len(raw) == 65
    assert raw[0] == 0x04  # uncompressed-point marker


@pytest.mark.unit
def test_send_returns_true_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(push, "_keys_path", lambda: str(tmp_path / "vapid.pem"))

    with patch("api.push.webpush") as mock_webpush:
        mock_webpush.return_value = None

        ok = push.send(
            {"endpoint": "https://push.example/x", "keys": {"p256dh": "a", "auth": "b"}},
            {"title": "Done"},
            "mailto:test@example.com",
        )

    assert ok is True
    mock_webpush.assert_called_once()


@pytest.mark.unit
def test_send_never_raises_on_a_dead_subscription(tmp_path, monkeypatch):
    """A revoked/expired subscription is the normal case, not an edge case
    -- browsers drop subscriptions silently and the first anyone finds out
    is the next failed send. Must degrade to False, never raise, and never
    make the caller wait on real network I/O for this unit test."""
    from pywebpush import WebPushException

    monkeypatch.setattr(push, "_keys_path", lambda: str(tmp_path / "vapid.pem"))

    with patch("api.push.webpush", side_effect=WebPushException("410 Gone")):
        ok = push.send(
            {"endpoint": "https://push.example/dead", "keys": {"p256dh": "a", "auth": "b"}},
            {"title": "Done"},
            "mailto:test@example.com",
        )

    assert ok is False


@pytest.mark.unit
def test_send_never_raises_on_a_completely_malformed_subscription(tmp_path, monkeypatch):
    """Defends the broad except in send(): even an error type pywebpush
    itself doesn't raise (a bad subscription_info shape, for instance)
    must not escape -- this function's contract is "never touches the run
    it's reporting on," full stop."""
    monkeypatch.setattr(push, "_keys_path", lambda: str(tmp_path / "vapid.pem"))

    with patch("api.push.webpush", side_effect=KeyError("keys")):
        ok = push.send({"endpoint": "not-even-a-real-shape"}, {"title": "Done"}, "mailto:t@e.com")

    assert ok is False


# --- store layer ---------------------------------------------------------


@pytest.fixture
def store(tmp_path):
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


@pytest.mark.unit
def test_a_run_with_no_subscribers_returns_an_empty_list(store):
    result = _run(store.get_push_subscriptions("no-such-run"))

    assert result == []


@pytest.mark.unit
def test_add_and_get_push_subscription_round_trips(store):
    async def scenario():
        created = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        await store.add_push_subscription(
            created.id, "https://push.example/x", "p256dh-key", "auth-key"
        )
        return await store.get_push_subscriptions(created.id)

    subs = _run(scenario())

    assert len(subs) == 1
    assert subs[0].endpoint == "https://push.example/x"
    assert subs[0].p256dh == "p256dh-key"
    assert subs[0].auth == "auth-key"


@pytest.mark.unit
def test_a_run_can_have_multiple_subscribers(store):
    """Several tabs/devices watching the same run each get their own row --
    all of them should be notified, not just the first."""

    async def scenario():
        created = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        await store.add_push_subscription(created.id, "https://push.example/a", "k1", "a1")
        await store.add_push_subscription(created.id, "https://push.example/b", "k2", "a2")
        return await store.get_push_subscriptions(created.id)

    subs = _run(scenario())

    assert {s.endpoint for s in subs} == {"https://push.example/a", "https://push.example/b"}


@pytest.mark.unit
def test_clear_push_subscriptions_removes_only_that_runs_rows(store):
    async def scenario():
        run_a = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST)
        run_b = await store.create("TCS.NS", DAY, AnalysisProfile.FAST)
        await store.add_push_subscription(run_a.id, "https://push.example/a", "k1", "a1")
        await store.add_push_subscription(run_b.id, "https://push.example/b", "k2", "a2")

        await store.clear_push_subscriptions(run_a.id)

        return (
            await store.get_push_subscriptions(run_a.id),
            await store.get_push_subscriptions(run_b.id),
        )

    remaining_a, remaining_b = _run(scenario())

    assert remaining_a == []
    assert len(remaining_b) == 1


# --- HTTP layer ------------------------------------------------------------


@pytest.fixture
def client_and_store(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.dependencies import InMemoryRunStore, get_run_store
    from api.main import create_app

    monkeypatch.setattr(push, "_keys_path", lambda: str(tmp_path / "vapid.pem"))
    push._vapid = None

    app = create_app()
    run_store = InMemoryRunStore()
    app.dependency_overrides[get_run_store] = lambda: run_store
    with TestClient(app) as test_client:
        yield test_client, run_store


@pytest.mark.unit
def test_vapid_public_key_endpoint_returns_a_key(client_and_store):
    client, _store = client_and_store

    response = client.get("/push/vapid-public-key")

    assert response.status_code == 200
    assert len(response.json()["key"]) > 0


@pytest.mark.unit
def test_subscribe_endpoint_stores_a_subscription_for_a_running_run(client_and_store):
    client, run_store = client_and_store
    created_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]

    response = client.post(
        f"/runs/{created_id}/subscribe",
        json={
            "endpoint": "https://push.example/x",
            "keys": {"p256dh": "p-key", "auth": "a-key"},
        },
    )

    assert response.status_code == 204
    subs = _run(run_store.get_push_subscriptions(created_id))
    assert len(subs) == 1
    assert subs[0].endpoint == "https://push.example/x"


@pytest.mark.unit
def test_subscribe_endpoint_404s_for_an_unknown_run(client_and_store):
    client, _store = client_and_store

    response = client.post(
        "/runs/does-not-exist/subscribe",
        json={"endpoint": "https://push.example/x", "keys": {"p256dh": "p", "auth": "a"}},
    )

    assert response.status_code == 404


@pytest.mark.unit
def test_subscribe_endpoint_404s_for_an_already_finished_run(client_and_store):
    client, run_store = client_and_store
    created_id = client.post("/analyze", json={"ticker": "SIEMENS.NS"}).json()["id"]
    run_store._runs[created_id] = run_store._runs[created_id].model_copy(
        update={"status": RunStatus.COMPLETED}
    )

    response = client.post(
        f"/runs/{created_id}/subscribe",
        json={"endpoint": "https://push.example/x", "keys": {"p256dh": "p", "auth": "a"}},
    )

    assert response.status_code == 404
