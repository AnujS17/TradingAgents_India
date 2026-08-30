"""POST /auth/register and POST /auth/login: email+password accounts,
alongside the existing Google OAuth path (tests/test_auth_bootstrap.py).

Follows the same fixture pattern as test_auth_bootstrap.py: a real
TestClient against a fresh, real SQLite database, with no
get_current_user override -- the whole point is to exercise the actual
sign-in-then-use-a-protected-route chain, not a stand-in for it.
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.db as db_module
import api.routers.auth as auth_router_module
from api.db import Base, User


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sessionmaker(tmp_path, monkeypatch):
    from api.settings import get_settings

    monkeypatch.setenv("TRADINGAGENTS_API_JWT_SECRET", "test-secret-do-not-use-in-prod-32chars")
    get_settings.cache_clear()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())

    monkeypatch.setattr(db_module, "_engine", engine, raising=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker, raising=False)

    # The login-attempt throttle is process-global state (api.routers.auth's
    # own module dict) -- reset it per test so one test's failed attempts
    # can't bleed into the next and produce a spurious 429.
    auth_router_module._recent_failed_logins.clear()

    yield maker

    asyncio.run(engine.dispose())
    get_settings.cache_clear()


@pytest.fixture
def client(sessionmaker):
    from api.dependencies import InMemoryRunStore, get_run_store
    from api.main import create_app

    app = create_app()
    app.dependency_overrides[get_run_store] = lambda: InMemoryRunStore()
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
def test_registering_creates_a_users_row_with_a_hashed_password(client, sessionmaker):
    resp = client.post(
        "/auth/register", json={"email": "a@x.com", "password": "correct-horse-battery", "name": "A"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "a@x.com"
    assert body["sub"].startswith("local:")

    async def fetch():
        async with sessionmaker() as session:
            result = await session.execute(select(User).where(User.email == "a@x.com"))
            return result.scalar_one()

    user = _run(fetch())
    assert user.password_hash is not None
    assert user.password_hash != "correct-horse-battery"  # never stored in the clear


@pytest.mark.unit
def test_registering_twice_with_the_same_email_is_rejected(client):
    first = client.post("/auth/register", json={"email": "a@x.com", "password": "correct-horse-battery"})
    assert first.status_code == 201

    second = client.post("/auth/register", json={"email": "a@x.com", "password": "a-different-password"})
    assert second.status_code == 409


@pytest.mark.unit
def test_a_password_shorter_than_8_chars_is_rejected():
    from api.dependencies import InMemoryRunStore, get_run_store
    from api.main import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    app.dependency_overrides[get_run_store] = lambda: InMemoryRunStore()
    with TestClient(app) as client:
        resp = client.post("/auth/register", json={"email": "a@x.com", "password": "short1"})
    assert resp.status_code == 422


@pytest.mark.unit
def test_login_with_the_correct_password_succeeds(client):
    client.post("/auth/register", json={"email": "a@x.com", "password": "correct-horse-battery"})

    resp = client.post("/auth/login", json={"email": "a@x.com", "password": "correct-horse-battery"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "a@x.com"


@pytest.mark.unit
def test_login_with_the_wrong_password_is_rejected(client):
    client.post("/auth/register", json={"email": "a@x.com", "password": "correct-horse-battery"})

    resp = client.post("/auth/login", json={"email": "a@x.com", "password": "wrong-password"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


@pytest.mark.unit
def test_login_for_an_email_with_no_account_returns_the_same_generic_error(client):
    resp = client.post("/auth/login", json={"email": "nobody@x.com", "password": "whatever-12345"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


@pytest.mark.unit
def test_login_against_a_google_only_account_with_no_password_set_is_rejected(client, sessionmaker):
    """A Google-signed-in account has password_hash=None -- logging in with
    ANY password for that email must fail, not succeed because "no hash to
    compare against" was mistaken for "any password is fine."""
    from api.auth import get_or_create_user

    _run(
        get_or_create_user(
            sessionmaker, google_sub="google-sub-1", email="google-user@x.com", name="G", picture=None
        )
    )

    resp = client.post("/auth/login", json={"email": "google-user@x.com", "password": "anything-at-all"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


@pytest.mark.unit
def test_repeated_failed_logins_are_rate_limited(client):
    client.post("/auth/register", json={"email": "a@x.com", "password": "correct-horse-battery"})

    for _ in range(10):
        resp = client.post("/auth/login", json={"email": "a@x.com", "password": "wrong-password"})
        assert resp.status_code == 401

    limited = client.post("/auth/login", json={"email": "a@x.com", "password": "wrong-password"})
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


@pytest.mark.unit
def test_login_then_a_protected_route_succeeds_with_the_resulting_identity(client):
    """The same end-to-end property test_auth_bootstrap.py proves for
    Google: no get_current_user override anywhere, so the 401 that would
    fire for an unknown sub is live -- the only thing making the follow-up
    call succeed is that /auth/login's returned `sub` really does identify
    a real row NextAuth can mint a valid token for."""
    import jwt

    SECRET = "test-secret-do-not-use-in-prod-32chars"

    client.post("/auth/register", json={"email": "a@x.com", "password": "correct-horse-battery", "name": "A"})
    login = client.post("/auth/login", json={"email": "a@x.com", "password": "correct-horse-battery"})
    assert login.status_code == 200
    sub = login.json()["sub"]

    # Mint the token the SAME way NextAuth's jwt.encode does (sub/role/tier
    # claims, HS256, this test's own SECRET matching the fixture's env
    # var) -- this test doesn't exercise the Node side, only that the
    # backend identity /auth/login handed back is a real, usable one.
    token = jwt.encode({"sub": sub, "role": "user", "tier": "free"}, SECRET, algorithm="HS256")
    payload = {"ticker": "SIEMENS.NS", "analysis_date": "2026-08-26", "profile": "fast"}

    resp = client.post("/analyze", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (200, 202), f"protected route rejected a freshly-registered user: {resp.status_code} {resp.text}"
