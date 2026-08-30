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

from fastapi import APIRouter, Header, HTTPException

from api.auth import InvalidToken, decode_token, get_or_create_user
from api.db import get_sessionmaker

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_FAILURE_DETAIL = "Not authenticated"


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
