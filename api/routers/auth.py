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
from api.ratelimit import BudgetExceeded, client_identity
from api.schemas import AuthUser, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_FAILURE_DETAIL = "Not authenticated"
_LOGIN_FAILURE_DETAIL = "Invalid email or password"

# Failed-login throttle, keyed by client_identity (IP). In-process only --
# adequate for a single Uvicorn worker the same way db.py's guarded
# ALTER TABLE is "adequate while the schema moves daily rather than
# reaching for Alembic": it blunts a straightforward password-guessing
# script without needing a shared store (Redis is a listed dependency in
# this repo but genuinely unused elsewhere; wiring it in for this alone
# would be new production infrastructure, not a fix). Resets on process
# restart and does not share state across multiple worker processes --
# both acceptable for a login-throttle (unlike the run-spend budget in
# api.ratelimit, which deliberately reads the database for exactly the
# opposite reason).
_LOGIN_ATTEMPT_WINDOW_SECONDS = 15 * 60
_LOGIN_ATTEMPT_MAX = 10
_recent_failed_logins: dict[str, list[float]] = {}


def _check_login_rate_limit(identity: str) -> None:
    now = time.monotonic()
    attempts = [t for t in _recent_failed_logins.get(identity, []) if now - t < _LOGIN_ATTEMPT_WINDOW_SECONDS]
    if len(attempts) >= _LOGIN_ATTEMPT_MAX:
        raise BudgetExceeded(
            "Too many login attempts. Try again later.",
            retry_after_seconds=_LOGIN_ATTEMPT_WINDOW_SECONDS,
        )
    _recent_failed_logins[identity] = attempts


def _record_failed_login(identity: str) -> None:
    _recent_failed_logins.setdefault(identity, []).append(time.monotonic())


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
async def register(payload: RegisterRequest) -> AuthUser:
    """Create a password account. Does not sign the caller in -- the
    frontend calls POST /auth/login right after a successful registration
    (NextAuth's Credentials `signIn`), so there is exactly one code path
    that turns email+password into a session, not two to keep in sync."""
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
    (web/app/src/lib/auth.ts) does that, the same as for Google."""
    identity = client_identity(request)
    _check_login_rate_limit(identity)

    user = await authenticate_password_user(get_sessionmaker(), email=payload.email, password=payload.password)
    if user is None:
        _record_failed_login(identity)
        # One message for "no such email", "Google-only account with no
        # password set", and "wrong password" alike -- same anti-
        # enumeration principle as get_current_user's uniform 401.
        raise HTTPException(status_code=401, detail=_LOGIN_FAILURE_DETAIL)

    return AuthUser(sub=user.google_sub, email=user.email, name=user.name, picture=user.picture)
