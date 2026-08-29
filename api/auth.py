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
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
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
    one after is role="user". The count-and-decide and the INSERT are done
    as a *single* SQL statement (INSERT ... SELECT with the role computed
    by a CASE against a subquery on the same table) rather than a
    SELECT-then-INSERT pair. SQLite only ever lets one writer hold the
    write lock at a time, and that lock is held for the statement/
    transaction's whole duration -- so a two-statement "read the count,
    then insert" leaves a window where a second connection's read can
    observe the same pre-insert count before the first has committed
    (both becoming admin). Folding it into one statement removes that
    window: the inner COUNT(*) is evaluated against the table's committed
    state as of this statement's start, and no other connection's write
    can interleave inside it.

    If a *second* login for the SAME google_sub races this one (e.g. a
    double-tab first login), the UNIQUE constraint on google_sub makes the
    loser's INSERT raise IntegrityError -- caught below, and handled by
    re-selecting and returning the winner's row rather than raising.
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

        new_id = new_run_id()
        created_at = utcnow()
        insert_stmt = text(
            """
            INSERT INTO users (id, google_sub, email, name, picture, role, tier, created_at, last_login_at)
            SELECT :id, :google_sub, :email, :name, :picture,
                   CASE WHEN (SELECT COUNT(*) FROM users) = 0 THEN 'admin' ELSE 'user' END,
                   'free', :created_at, :created_at
            """
        )
        try:
            await session.execute(
                insert_stmt,
                {
                    "id": new_id,
                    "google_sub": google_sub,
                    "email": email,
                    "name": name,
                    "picture": picture,
                    "created_at": created_at,
                },
            )
            await session.commit()
        except IntegrityError:
            # Someone else's INSERT for this exact google_sub won the race
            # between our "not found" lookup above and our own INSERT.
            # That row is the real one now -- fetch and return it instead
            # of surfacing a raw constraint-violation error to the caller.
            await session.rollback()
            existing_after = await session.execute(select(User).where(User.google_sub == google_sub))
            user = existing_after.scalar_one_or_none()
            if user is None:
                raise
            return user

        result = await session.execute(select(User).where(User.google_sub == google_sub))
        user = result.scalar_one()

        if user.role == "admin":
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
    deliberately identical, INCLUDING the response body's `detail` string,
    so nothing about WHY a token failed leaks to an unauthenticated
    caller. (Distinct log messages / exception chaining server-side are
    fine -- it's only the value that crosses the wire that must not vary.)
    """
    _AUTH_FAILURE_DETAIL = "Not authenticated"

    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail=_AUTH_FAILURE_DETAIL, headers={"WWW-Authenticate": "Bearer"})

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_token(token)
    except InvalidToken as exc:
        raise HTTPException(status_code=401, detail=_AUTH_FAILURE_DETAIL, headers={"WWW-Authenticate": "Bearer"}) from exc

    user = await _find_user_by_sub(claims["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail=_AUTH_FAILURE_DETAIL, headers={"WWW-Authenticate": "Bearer"})

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
