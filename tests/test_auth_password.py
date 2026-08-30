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

    # The login/register throttles are process-global state (api.routers.
    # auth's own module dicts) -- reset per test so one test's attempts
    # can't bleed into the next and produce a spurious 429.
    auth_router_module._recent_failed_logins.clear()
    auth_router_module._recent_registrations.clear()

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


@pytest.mark.unit
def test_registering_on_a_fresh_database_never_becomes_admin(client, sessionmaker):
    """The very first row on a fresh database is normally admin
    (test_auth.py::test_the_first_ever_signin_becomes_admin) -- but that
    bootstrap must only be reachable through Google's OAuth handshake, not
    through POST /auth/register, an unauthenticated HTTP endpoint anyone
    can script against a fresh deployment before its operator ever signs
    in for the first time."""
    resp = client.post("/auth/register", json={"email": "attacker@evil.com", "password": "attacker-password-1"})
    assert resp.status_code == 201

    async def fetch():
        async with sessionmaker() as session:
            result = await session.execute(select(User).where(User.email == "attacker@evil.com"))
            return result.scalar_one()

    user = _run(fetch())
    assert user.role == "user", "an anonymous registration became admin"


@pytest.mark.unit
def test_a_google_signin_after_a_password_registration_for_the_same_email_is_rejected(client):
    """The reverse of test_registering_twice_with_the_same_email_is_rejected
    -- users.email is UNIQUE regardless of which side registered first."""
    reg = client.post("/auth/register", json={"email": "victim@x.com", "password": "correct-horse-battery"})
    assert reg.status_code == 201

    from api.auth import EmailAlreadyRegistered, get_or_create_user

    with pytest.raises(EmailAlreadyRegistered):
        _run(
            get_or_create_user(
                _current_sessionmaker(), google_sub="1234567890", email="victim@x.com", name="V", picture=None
            )
        )


@pytest.mark.unit
def test_registering_with_a_different_case_email_is_still_rejected_as_a_duplicate(client):
    first = client.post("/auth/register", json={"email": "victim@x.com", "password": "correct-horse-battery"})
    assert first.status_code == 201

    second = client.post("/auth/register", json={"email": "Victim@X.com", "password": "a-different-password-2"})
    assert second.status_code == 409


@pytest.mark.unit
def test_logging_in_with_a_different_case_email_still_finds_the_account(client):
    client.post("/auth/register", json={"email": "victim@x.com", "password": "correct-horse-battery"})

    resp = client.post("/auth/login", json={"email": "Victim@X.com", "password": "correct-horse-battery"})
    assert resp.status_code == 200


@pytest.mark.unit
def test_registration_attempts_are_rate_limited_regardless_of_success(client):
    for i in range(10):
        resp = client.post("/auth/register", json={"email": f"user{i}@x.com", "password": "correct-horse-battery"})
        assert resp.status_code == 201

    limited = client.post("/auth/register", json={"email": "one-more@x.com", "password": "correct-horse-battery"})
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


@pytest.mark.unit
def test_the_login_rate_limit_ignores_a_spoofed_x_forwarded_for_header(client):
    """api.ratelimit.client_identity trusts X-Forwarded-For unconditionally
    (documented there as a cost guardrail, not a security control) -- the
    login/register throttle must NOT use it, or an attacker defeats the
    whole limit with one extra header per request."""
    for i in range(auth_router_module._LOGIN_ATTEMPT_MAX):
        resp = client.post(
            "/auth/login",
            json={"email": "a@x.com", "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
        assert resp.status_code == 401, "a spoofed X-Forwarded-For must not bypass the throttle"

    still_limited = client.post(
        "/auth/login",
        json={"email": "a@x.com", "password": "wrong-password"},
        headers={"X-Forwarded-For": "10.0.0.99"},
    )
    assert still_limited.status_code == 429


@pytest.mark.unit
def test_a_distinct_bucket_tracks_failed_logins_per_target_email(client):
    """A distributed attack (many source IPs, one target email) must still
    be caught -- an IP-only bucket alone would let it through unbounded.
    TestClient issues every request from the same fixed host, so this
    checks the throttle's own state directly rather than simulating
    distinct source IPs it cannot actually produce: the email-keyed
    bucket (independent of whatever key the IP bucket used) must exist
    and grow with each failure."""
    for _ in range(3):
        resp = client.post("/auth/login", json={"email": "victim@x.com", "password": "wrong-password"})
        assert resp.status_code == 401

    assert len(auth_router_module._recent_failed_logins.get("email:victim@x.com", [])) == 3


@pytest.mark.unit
def test_a_422_response_never_echoes_the_submitted_password(client):
    # A distinctive value, not "short" -- Pydantic's own error type for
    # this case is literally named "string_too_short", which would make a
    # naive substring check on that word pass even if input redaction
    # were broken.
    submitted_password = "hunter2"
    resp = client.post("/auth/register", json={"email": "a@x.com", "password": submitted_password})
    assert resp.status_code == 422
    assert submitted_password not in resp.text


def _current_sessionmaker():
    from api.db import get_sessionmaker

    return get_sessionmaker()
