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
