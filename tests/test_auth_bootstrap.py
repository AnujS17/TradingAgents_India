"""POST /auth/bootstrap: the one production code path that creates a
``users`` row.

Before this endpoint existed, ``get_or_create_user`` was fully implemented
and fully unit-tested (see tests/test_auth.py) but never called by anything
outside those tests -- so the users table stayed empty forever and every
authenticated request 401'd in ``get_current_user``'s "no matching row"
branch. Every ownership test in the suite hid that by overriding the
``get_current_user`` dependency outright.

The last test in this file is the one that would have caught it: it drives a
real TestClient with NO dependency override on ``get_current_user``, signs in
via /auth/bootstrap, then calls an ordinary protected route with the same
token and requires it to succeed.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.db as db_module
from api.db import Base, User

SECRET = "test-secret-do-not-use-in-prod-32chars"


def _token(payload: dict, secret: str = SECRET) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    return jwt.encode({"exp": exp, **payload}, secret, algorithm="HS256")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sessionmaker(tmp_path, monkeypatch):
    """A fresh, empty database wired in as the process-wide one.

    ``api.routers.auth`` calls ``api.db.get_sessionmaker()`` and
    ``api.auth._find_user_by_sub`` calls it too, so pointing the module's
    cached engine at this temp file is what makes both the endpoint and
    ``get_current_user`` read and write the same throwaway database.
    """
    from api.settings import get_settings

    monkeypatch.setenv("TRADINGAGENTS_API_JWT_SECRET", SECRET)
    get_settings.cache_clear()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())

    monkeypatch.setattr(db_module, "_engine", engine, raising=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker, raising=False)

    yield maker

    asyncio.run(engine.dispose())
    get_settings.cache_clear()


@pytest.fixture
def client(sessionmaker):
    """The real app, with only the run store swapped for an in-memory one.

    Deliberately does NOT override ``get_current_user`` -- that override is
    exactly what made this whole class of bug invisible to the rest of the
    suite.
    """
    from api.dependencies import InMemoryRunStore, get_run_store
    from api.main import create_app

    app = create_app()
    app.dependency_overrides[get_run_store] = lambda: InMemoryRunStore()
    # create_app's lifespan runs create_tables() against the monkeypatched
    # engine, which the sessionmaker fixture already created the schema on --
    # create_all is a no-op the second time.
    with TestClient(app) as test_client:
        yield test_client


def _users(maker) -> list[User]:
    async def query():
        async with maker() as session:
            result = await session.execute(select(User))
            return list(result.scalars())

    return _run(query())


@pytest.mark.unit
def test_a_signed_token_creates_the_users_row(client, sessionmaker):
    token = _token({"sub": "google-abc", "email": "a@x.com", "name": "A", "picture": "https://p/a.png"})

    resp = client.post("/auth/bootstrap", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 204, resp.text
    rows = _users(sessionmaker)
    assert [r.google_sub for r in rows] == ["google-abc"]
    assert rows[0].email == "a@x.com"
    assert rows[0].name == "A"
    assert rows[0].picture == "https://p/a.png"


@pytest.mark.unit
def test_bootstrapping_twice_is_idempotent(client, sessionmaker):
    """A user signing in again (new browser, expired session) must not
    create a second row -- get_or_create_user already dedups on google_sub,
    and this pins that the endpoint actually reuses that behaviour."""
    token = _token({"sub": "google-abc", "email": "a@x.com", "name": "A", "picture": None})

    first = client.post("/auth/bootstrap", headers={"Authorization": f"Bearer {token}"})
    second = client.post("/auth/bootstrap", headers={"Authorization": f"Bearer {token}"})

    assert (first.status_code, second.status_code) == (204, 204)
    assert len(_users(sessionmaker)) == 1


@pytest.mark.unit
def test_the_first_bootstrap_in_an_empty_database_becomes_admin(client, sessionmaker):
    """The first-admin bootstrap exercised through the real HTTP path, not
    just get_or_create_user in isolation -- that isolated test passed for
    the entire time this could never actually fire in production."""
    token = _token({"sub": "google-first", "email": "first@x.com", "name": "First", "picture": None})

    resp = client.post("/auth/bootstrap", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 204, resp.text
    rows = _users(sessionmaker)
    assert rows[0].role == "admin"


@pytest.mark.unit
def test_a_missing_authorization_header_is_rejected(client, sessionmaker):
    resp = client.post("/auth/bootstrap")

    assert resp.status_code == 401
    assert _users(sessionmaker) == []


@pytest.mark.unit
def test_a_header_with_no_bearer_prefix_is_rejected(client, sessionmaker):
    resp = client.post("/auth/bootstrap", headers={"Authorization": "Basic dXNlcjpwYXNz"})

    assert resp.status_code == 401
    assert _users(sessionmaker) == []


@pytest.mark.unit
def test_a_token_signed_with_the_wrong_secret_is_rejected(client, sessionmaker):
    """This endpoint skips the "row must already exist" check, not the
    signature check -- an unsigned or wrongly-signed token would otherwise
    let anyone mint themselves an account (and the very first one an
    admin)."""
    forged = _token({"sub": "attacker", "email": "attacker@x.com"}, secret="a-completely-different-secret-32c")

    resp = client.post("/auth/bootstrap", headers={"Authorization": f"Bearer {forged}"})

    assert resp.status_code == 401
    assert _users(sessionmaker) == []


@pytest.mark.unit
def test_a_token_missing_the_email_claim_is_a_400_not_a_silent_no_op(client, sessionmaker):
    token = _token({"sub": "google-abc", "name": "A"})  # no "email"

    resp = client.post("/auth/bootstrap", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 400, resp.text
    assert _users(sessionmaker) == []


@pytest.mark.unit
def test_bootstrap_then_a_protected_route_succeeds_with_the_same_token(client, sessionmaker):
    """THE regression test for this fix.

    No ``dependency_overrides[get_current_user]`` anywhere: the 401 that
    ``get_current_user`` raises for a sub with no users row is live, and the
    only thing that stops it firing is the row /auth/bootstrap just created.
    Assert the protected call fails first WITHOUT the bootstrap, so this
    test cannot pass for the wrong reason.
    """
    token = _token({"sub": "new-user", "email": "new@x.com", "name": "New", "picture": None})
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"ticker": "SIEMENS.NS", "analysis_date": "2026-08-26", "profile": "fast"}

    before = client.post("/analyze", json=payload, headers=headers)
    assert before.status_code == 401, (
        "precondition: a valid token with no users row must be rejected -- if this "
        "is not 401 the test below proves nothing"
    )

    assert client.post("/auth/bootstrap", headers=headers).status_code == 204

    after = client.post("/analyze", json=payload, headers=headers)
    assert after.status_code in (200, 202), f"protected route still rejected after bootstrap: {after.status_code} {after.text}"
