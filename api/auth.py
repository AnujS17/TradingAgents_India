"""JWT verification for the API's half of the auth split.

NextAuth (the Next.js frontend) issues the token; this module only ever
verifies one, never issues one -- FastAPI has no login endpoint. See
docs/superpowers/specs/2026-08-29-auth-rbac-design.md for the full
architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.settings import get_settings

if TYPE_CHECKING:
    from api.db import User


class InvalidToken(Exception):
    """Any reason a bearer token cannot be trusted: expired, malformed,
    wrong signature, or missing a required claim. Deliberately one
    exception type, not one per failure mode -- every caller's response is
    identical (401), so there is nothing for a caller to branch on, and a
    single type keeps decode_token's contract simple to test against."""


def decode_token(token: str) -> dict:
    """Verify a bearer token's signature and return its claims.

    HS256 only, explicitly named -- PyJWT refuses "alg: none" and any
    algorithm not in this list by construction, so this line is also what
    closes the classic unsigned-JWT bypass (see
    test_alg_none_is_rejected_even_if_the_token_claims_it).
    """
    if not token:
        raise InvalidToken("empty token")

    secret = get_settings().jwt_secret
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc

    if "sub" not in claims:
        raise InvalidToken("token missing 'sub' claim")

    return claims


@dataclass(frozen=True)
class CurrentUser:
    """The subset of a User row request handlers actually need. A
    dataclass, not the SQLAlchemy row itself, so a handler can never
    accidentally trigger a lazy-load outside the session that fetched it."""

    id: str
    role: str
    tier: str


async def get_or_create_user(
    sessionmaker: async_sessionmaker,
    *,
    google_sub: str,
    email: str,
    name: str | None,
    picture: str | None,
) -> User:
    """Look up a user by Google's stable `sub`, or create one.

    The first row ever inserted into `users` becomes role="admin"; every
    one after is role="user". The COUNT and the INSERT happen in the same
    transaction so two simultaneous first-logins cannot both become admin
    -- SQLite serialises writers (api/db.py's own documented limit), which
    is exactly the property this relies on.
    """
    from api.db import User, new_run_id, utcnow

    async with sessionmaker() as session:
        existing = await session.execute(select(User).where(User.google_sub == google_sub))
        user = existing.scalar_one_or_none()
        if user is not None:
            user.last_login_at = utcnow()
            user.email = email
            user.name = name
            user.picture = picture
            await session.commit()
            await session.refresh(user)
            return user

        count = (await session.execute(select(func.count(User.id)))).scalar_one()
        role = "admin" if count == 0 else "user"

        user = User(
            id=new_run_id(),
            google_sub=google_sub,
            email=email,
            name=name,
            picture=picture,
            role=role,
            created_at=utcnow(),
            last_login_at=utcnow(),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        if role == "admin":
            from api.db import Run

            await session.execute(update(Run).where(Run.user_id.is_(None)).values(user_id=user.id))
            await session.commit()

        return user


async def _find_user_by_sub(google_sub: str) -> "User | None":
    from api.db import User, get_sessionmaker

    async with get_sessionmaker()() as session:
        result = await session.execute(select(User).where(User.google_sub == google_sub))
        return result.scalar_one_or_none()


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """FastAPI dependency: verify the bearer token and load its user.

    401 for every failure mode -- missing header, wrong scheme, bad
    signature, expired, or a sub with no matching row (deleted account) --
    deliberately identical, so nothing about WHY a token failed leaks to
    an unauthenticated caller.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_token(token)
    except InvalidToken as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from exc

    user = await _find_user_by_sub(claims["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="Account not found", headers={"WWW-Authenticate": "Bearer"})

    return CurrentUser(id=user.id, role=user.role, tier=user.tier)


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """FastAPI dependency: get_current_user, plus a role check. Not used by
    any Phase 1 route directly (ownership checks cover the per-run 404
    case) -- exists now because Task 6's ownership-check helper reads
    current_user.role == "admin" directly, and this dependency is the one
    later phases (an admin API) will actually import."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
AdminUserDep = Annotated[CurrentUser, Depends(require_admin)]
