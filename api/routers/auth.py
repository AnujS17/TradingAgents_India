"""Bootstraps a users row on first sign-in.

The ONLY endpoint in this app that accepts a structurally valid token for a
user who does not yet have a row -- every other endpoint (via
``api.auth.get_current_user``) requires the row to already exist, precisely so
a deleted account's still-valid token is rejected rather than silently
resurrecting it. This endpoint is the one deliberate exception: NextAuth's
``signIn`` callback (``web/app/src/lib/auth.ts``) calls it exactly once per
genuine OAuth handshake, never on ordinary token refresh or from a page load.

Without it nothing in production ever calls ``get_or_create_user``, so the
users table stays empty forever and every authenticated request 401s -- the
first-admin bootstrap and the legacy-run backfill living inside that function
never fire either.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException, Request

from api.auth import (
    EmailAlreadyRegistered,
    InvalidToken,
    authenticate_password_user,
    create_password_user,
    decode_token,
    get_or_create_user,
)
from api.db import get_sessionmaker
from api.ratelimit import BudgetExceeded
from api.schemas import AuthUser, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_FAILURE_DETAIL = "Not authenticated"
_LOGIN_FAILURE_DETAIL = "Invalid email or password"

# Failed-login / registration throttle. In-process only -- adequate for a
# single Uvicorn worker the same way db.py's guarded ALTER TABLE is
# "adequate while the schema moves daily rather than reaching for
# Alembic": it blunts a straightforward password-guessing or account-
# creation script without needing a shared store (Redis is a listed
# dependency in this repo but genuinely unused elsewhere; wiring it in for
# this alone would be new production infrastructure, not a fix). Resets
# on process restart and does not share state across multiple worker
# processes -- both acceptable for a login-throttle (unlike the run-spend
# budget in api.ratelimit, which deliberately reads the database for
# exactly the opposite reason).
_LOGIN_ATTEMPT_WINDOW_SECONDS = 15 * 60
_LOGIN_ATTEMPT_MAX = 10
_REGISTER_ATTEMPT_MAX = 10
_recent_failed_logins: dict[str, list[float]] = {}
_recent_registrations: dict[str, list[float]] = {}
# Caps total tracked identities so an attacker rotating a spoofed identity
# per request (see _client_identity below) can't grow either dict without
# bound -- entries are only otherwise pruned when their OWN key is hit
# again, which a rotating attacker never does twice.
_MAX_TRACKED_IDENTITIES = 10_000


def _client_identity(request: Request) -> str:
    """IP only -- deliberately NOT api.ratelimit.client_identity, which
    trusts X-Forwarded-For unconditionally (its own docstring: "This is
    spoofable. It is a cost guardrail, not a security control"). That
    trade-off is fine for the run-spend budget it protects; a login/
    registration throttle IS meant to be a security control, and
    X-Forwarded-For being fully caller-controlled with no trusted-proxy
    list would make it worthless as one -- verified directly: a rotated
    header defeated the shared helper's identity on every single request.
    request.client.host is what the TCP connection actually terminated
    from, which the caller cannot spoof no matter what headers it sends.
    """
    return request.client.host if request.client else "unknown"


def _prune_stale_identities(buckets: dict[str, list[float]], now: float) -> None:
    if len(buckets) <= _MAX_TRACKED_IDENTITIES:
        return
    stale = [key for key, attempts in buckets.items() if not attempts or now - max(attempts) >= _LOGIN_ATTEMPT_WINDOW_SECONDS]
    for key in stale:
        del buckets[key]


def _check_rate_limit(buckets: dict[str, list[float]], identity: str, max_attempts: int, message: str) -> None:
    now = time.monotonic()
    _prune_stale_identities(buckets, now)
    attempts = [t for t in buckets.get(identity, []) if now - t < _LOGIN_ATTEMPT_WINDOW_SECONDS]
    if len(attempts) >= max_attempts:
        raise BudgetExceeded(message, retry_after_seconds=_LOGIN_ATTEMPT_WINDOW_SECONDS)
    buckets[identity] = attempts


def _record_attempt(buckets: dict[str, list[float]], identity: str) -> None:
    buckets.setdefault(identity, []).append(time.monotonic())


@router.post("/bootstrap", status_code=204)
async def bootstrap_user(authorization: str | None = Header(default=None)) -> None:
    """Upsert the caller's users row from their own verified token claims.

    Still requires a validly SIGNED token -- ``decode_token`` is the same
    verification every other route goes through. The only check this endpoint
    skips is "a row must already exist", which is the whole reason it exists.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail=_AUTH_FAILURE_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_token(token)
    except InvalidToken as exc:
        raise HTTPException(
            status_code=401,
            detail=_AUTH_FAILURE_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    email = claims.get("email")
    if not email:
        # 400, not a silent no-op: a token that verifies but carries no email
        # is a frontend bug (the jwt callback failed to forward the claim),
        # and swallowing it would put the user straight back into the
        # 401-forever state this endpoint exists to prevent.
        raise HTTPException(
            status_code=400, detail="Token is missing required claims for bootstrap"
        )

    await get_or_create_user(
        get_sessionmaker(),
        google_sub=claims["sub"],
        email=email,
        name=claims.get("name"),
        picture=claims.get("picture"),
    )


@router.post("/register", response_model=AuthUser, status_code=201)
async def register(payload: RegisterRequest, request: Request) -> AuthUser:
    """Create a password account. Does not sign the caller in -- the
    frontend calls POST /auth/login right after a successful registration
    (NextAuth's Credentials `signIn`), so there is exactly one code path
    that turns email+password into a session, not two to keep in sync.

    Throttled the same as login, counting every attempt (not just
    failures): unlike login, the concern here isn't guessing a password,
    it's volume -- each call runs a ~0.4s Argon2 hash (off the event loop,
    see api.auth.hash_password's docstring, but still real CPU work) and
    writes a row. An unthrottled endpoint that does both is a resource-
    exhaustion and database-spam vector even when every request succeeds.
    """
    identity = _client_identity(request)
    _check_rate_limit(_recent_registrations, identity, _REGISTER_ATTEMPT_MAX, "Too many registration attempts. Try again later.")
    _record_attempt(_recent_registrations, identity)

    try:
        user = await create_password_user(
            get_sessionmaker(), email=payload.email, password=payload.password, name=payload.name
        )
    except EmailAlreadyRegistered as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc

    return AuthUser(sub=user.google_sub, email=user.email, name=user.name, picture=user.picture)


@router.post("/login", response_model=AuthUser)
async def login(payload: LoginRequest, request: Request) -> AuthUser:
    """Verify email+password and return the account's identity claims for
    NextAuth's Credentials `authorize()` to build a token from -- the same
    downstream flow a Google sign-in produces, just a different front
    door. This endpoint issues no token itself; NextAuth's own jwt.encode
    (web/app/src/lib/auth.ts) does that, the same as for Google.

    Throttled on BOTH the caller's IP and the target email, independently
    -- an IP-only limit does nothing against a distributed attack (many
    IPs, one victim email); an email-only limit does nothing against one
    attacker spraying many candidate emails from a single IP. Either
    bucket tripping is enough to reject.
    """
    ip_identity = _client_identity(request)
    email_identity = f"email:{payload.email.strip().lower()}"
    _check_rate_limit(_recent_failed_logins, ip_identity, _LOGIN_ATTEMPT_MAX, "Too many login attempts. Try again later.")
    _check_rate_limit(_recent_failed_logins, email_identity, _LOGIN_ATTEMPT_MAX, "Too many login attempts. Try again later.")

    user = await authenticate_password_user(get_sessionmaker(), email=payload.email, password=payload.password)
    if user is None:
        _record_attempt(_recent_failed_logins, ip_identity)
        _record_attempt(_recent_failed_logins, email_identity)
        # One message for "no such email", "Google-only account with no
        # password set", and "wrong password" alike -- same anti-
        # enumeration principle as get_current_user's uniform 401.
        raise HTTPException(status_code=401, detail=_LOGIN_FAILURE_DETAIL)

    return AuthUser(sub=user.google_sub, email=user.email, name=user.name, picture=user.picture)
