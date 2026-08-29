"""JWT verification core. Adversarial by design -- this is the one gate
every protected request passes through, so every way a token can be wrong
gets its own test, not just the happy path."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from api.auth import InvalidToken, decode_token

SECRET = "test-secret-do-not-use-in-prod"


def _token(payload: dict, secret: str = SECRET, algorithm: str = "HS256", **jwt_kwargs) -> str:
    return jwt.encode(payload, secret, algorithm=algorithm, **jwt_kwargs)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    from api.settings import get_settings

    monkeypatch.setenv("TRADINGAGENTS_API_JWT_SECRET", SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.unit
def test_a_validly_signed_token_decodes_to_its_claims():
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    token = _token({"sub": "google-123", "role": "user", "tier": "free", "exp": exp})

    claims = decode_token(token)

    assert claims["sub"] == "google-123"
    assert claims["role"] == "user"


@pytest.mark.unit
def test_an_expired_token_is_rejected():
    exp = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = _token({"sub": "google-123", "exp": exp})

    with pytest.raises(InvalidToken):
        decode_token(token)


@pytest.mark.unit
def test_a_token_signed_with_the_wrong_secret_is_rejected():
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    token = _token({"sub": "google-123", "exp": exp}, secret="wrong-secret")

    with pytest.raises(InvalidToken):
        decode_token(token)


@pytest.mark.unit
def test_a_malformed_token_is_rejected():
    with pytest.raises(InvalidToken):
        decode_token("not-a-jwt-at-all")


@pytest.mark.unit
def test_an_empty_token_is_rejected():
    with pytest.raises(InvalidToken):
        decode_token("")


@pytest.mark.unit
def test_alg_none_is_rejected_even_if_the_token_claims_it():
    """The classic JWT bypass: a token with alg=none and no signature at
    all. PyJWT refuses to decode these by default as long as the caller
    passes an explicit algorithms list (never "accept whatever the token
    says") -- this test pins that we never regress into accepting it."""
    unsigned = jwt.encode({"sub": "attacker", "exp": 9999999999}, "", algorithm="none")

    with pytest.raises(InvalidToken):
        decode_token(unsigned)


@pytest.mark.unit
def test_a_token_missing_the_sub_claim_is_rejected():
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    token = _token({"exp": exp})  # no "sub"

    with pytest.raises(InvalidToken):
        decode_token(token)


import asyncio

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import Base, User


@pytest.fixture
def sessionmaker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
def test_the_first_ever_signin_becomes_admin(sessionmaker):
    from api.auth import get_or_create_user

    user = _run(get_or_create_user(sessionmaker, google_sub="sub-1", email="a@x.com", name="A", picture=None))

    assert user.role == "admin"


@pytest.mark.unit
def test_the_second_signin_is_a_plain_user(sessionmaker):
    from api.auth import get_or_create_user

    async def scenario():
        first = await get_or_create_user(sessionmaker, google_sub="sub-1", email="a@x.com", name="A", picture=None)
        second = await get_or_create_user(sessionmaker, google_sub="sub-2", email="b@x.com", name="B", picture=None)
        return first, second

    first, second = _run(scenario())
    assert first.role == "admin"
    assert second.role == "user"


@pytest.mark.unit
def test_a_repeat_signin_reuses_the_same_user_row_and_updates_last_login(sessionmaker):
    from api.auth import get_or_create_user

    async def scenario():
        first = await get_or_create_user(sessionmaker, google_sub="sub-1", email="a@x.com", name="A", picture=None)
        again = await get_or_create_user(sessionmaker, google_sub="sub-1", email="a@x.com", name="A", picture=None)
        return first, again

    first, again = _run(scenario())
    assert first.id == again.id
    assert again.last_login_at is not None


@pytest.mark.unit
def test_get_current_user_rejects_a_missing_authorization_header():
    from api.auth import get_current_user

    with pytest.raises(HTTPException) as exc_info:
        _run(get_current_user(authorization=None))
    assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_get_current_user_rejects_a_header_with_no_bearer_prefix():
    from api.auth import get_current_user

    with pytest.raises(HTTPException) as exc_info:
        _run(get_current_user(authorization="Basic dXNlcjpwYXNz"))
    assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_get_current_user_rejects_a_token_for_a_deleted_account(monkeypatch):
    """A structurally valid, correctly-signed token whose google_sub no
    longer has a matching row (account deleted) must not be trusted --
    forces re-auth rather than serving a ghost identity."""
    from datetime import datetime, timedelta, timezone

    import api.auth as auth_module

    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    token = _token({"sub": "sub-does-not-exist", "exp": exp})

    async def fake_lookup(sub):
        return None

    monkeypatch.setattr(auth_module, "_find_user_by_sub", fake_lookup)

    with pytest.raises(HTTPException) as exc_info:
        _run(auth_module.get_current_user(authorization=f"Bearer {token}"))
    assert exc_info.value.status_code == 401
