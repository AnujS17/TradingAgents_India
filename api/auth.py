"""JWT verification for the API's half of the auth split.

NextAuth (the Next.js frontend) issues the token; this module only ever
verifies one, never issues one -- FastAPI has no login endpoint. See
docs/superpowers/specs/2026-08-29-auth-rbac-design.md for the full
architecture.

Two ways to get a users row now: Google OAuth (get_or_create_user, called
from POST /auth/bootstrap) and a password account (create_password_user,
called from POST /auth/register). Both funnel through the same
_atomic_insert_user helper below -- the first-admin-bootstrap race
condition and the legacy-run backfill only need to be gotten right once.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.settings import get_settings

if TYPE_CHECKING:
    from api.db import User

# Argon2id, the current OWASP-recommended default -- memory-hard (costly to
# attack with GPUs/ASICs, unlike a bare SHA-256 or MD5 hash) and its own
# verify() is constant-time by construction, so no separate hmac.compare_
# digest dance is needed here the way it would be for a manual digest
# comparison.
_password_hasher = PasswordHasher()

# A precomputed hash of a value nobody will ever actually submit as a
# password. verify_password's "user not found" branch below still runs a
# real Argon2 verify against this instead of short-circuiting straight to
# False -- otherwise a nonexistent-email response returns measurably
# faster than a wrong-password one, and that timing difference is exactly
# what lets an attacker enumerate which emails have accounts.
_DUMMY_HASH = PasswordHasher().hash("this-hash-is-never-matched-by-a-real-login-attempt")


def hash_password(password: str) -> str:
    """Synchronous, CPU-bound (Argon2id at m=65536 KiB, t=3, p=4 -- roughly
    a third of a second per call). Callers MUST run this via
    asyncio.to_thread, never awaited directly on the request-handling
    coroutine: argon2-cffi's C implementation releases the GIL during the
    hash, so a thread genuinely parallelises it, but called inline it
    blocks this process's entire event loop -- every other in-flight
    request, including unrelated ones like an SSE run stream -- for the
    full duration. Measured directly: ~400ms of total event-loop freeze
    per call when this was awaited inline."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """True iff `password` matches `password_hash`. Always does the real
    Argon2 work (against _DUMMY_HASH when `password_hash` is None, i.e. no
    account or a Google-only account with no password set) so a caller
    cannot distinguish "no such account" / "no password set" / "wrong
    password" by response timing -- see _DUMMY_HASH's own comment. Same
    to_thread requirement as hash_password -- see its docstring."""
    try:
        _password_hasher.verify(password_hash or _DUMMY_HASH, password)
        return password_hash is not None
    except VerificationError:
        return False
    except InvalidHashError:
        # Not VerificationError's subclass (it's a ValueError) -- a
        # malformed/corrupt stored hash. Not reachable via hash_password's
        # own output today, but a future hash-format change or a
        # truncated column must fail the same way a wrong password does,
        # not surface as a 500 that would itself be an enumeration oracle
        # (500 = "this email has a broken hash", 401 = everything else).
        return False


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str | None) -> bool:
    return await asyncio.to_thread(verify_password, password, password_hash)


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


async def _atomic_insert_user(
    session,
    *,
    google_sub: str,
    email: str,
    name: str | None,
    picture: str | None,
    password_hash: str | None,
    allow_admin_bootstrap: bool,
) -> User:
    """INSERT one new users row, deciding admin-vs-user atomically, and
    backfill legacy ownerless runs onto it if it won admin. Shared by
    get_or_create_user (Google) and create_password_user (email/password)
    -- both need the identical race-free bootstrap logic, and duplicating
    it would risk the two drifting (one gaining the backfill fix, say,
    without the other).

    ``allow_admin_bootstrap`` gates whether THIS insert is even eligible to
    become the first-row admin -- create_password_user always passes
    False. Completing Google's OAuth handshake is a real, if imperfect,
    barrier (a browser, a Google account, the actual consent screen);
    POST /auth/register has none of that -- it is a plain unauthenticated
    HTTP endpoint. Without this gate, the very first `curl -X POST
    /auth/register` against a fresh deployment -- fully scriptable, no
    browser, no Google account, racing the operator's own first sign-in --
    would win admin and the entire legacy-run backfill. Verified directly
    (a security review executed exactly this against a fresh database
    before this gate existed) that it worked.

    The first row ever inserted into `users` becomes role="admin" only
    when this call is itself eligible AND the table is still empty; every
    other case is role="user". The count-and-decide and the INSERT are
    done as a *single* SQL statement (INSERT ... SELECT with the role
    computed by a CASE against a subquery on the same table) rather than a
    SELECT-then-INSERT pair. SQLite only ever lets one writer hold the
    write lock at a time, and that lock is held for the statement/
    transaction's whole duration -- so a two-statement "read the count,
    then insert" leaves a window where a second connection's read can
    observe the same pre-insert count before the first has committed
    (both becoming admin). Folding it into one statement removes that
    window: the inner COUNT(*) is evaluated against the table's committed
    state as of this statement's start, and no other connection's write
    can interleave inside it.

    Raises IntegrityError (uncaught) on a UNIQUE-constraint collision --
    the caller decides what that means for its own identity key
    (get_or_create_user's google_sub race vs. create_password_user's
    already-registered-email check).
    """
    from api.db import User, new_run_id, utcnow

    new_id = new_run_id()
    created_at = utcnow()
    role_case = (
        "CASE WHEN (SELECT COUNT(*) FROM users) = 0 THEN 'admin' ELSE 'user' END"
        if allow_admin_bootstrap
        else "'user'"
    )
    insert_stmt = text(
        f"""
        INSERT INTO users (id, google_sub, email, name, picture, password_hash, role, tier, created_at, last_login_at)
        SELECT :id, :google_sub, :email, :name, :picture, :password_hash,
               {role_case},
               'free', :created_at, :created_at
        """
    )
    await session.execute(
        insert_stmt,
        {
            "id": new_id,
            "google_sub": google_sub,
            "email": email,
            "name": name,
            "picture": picture,
            "password_hash": password_hash,
            "created_at": created_at,
        },
    )
    await session.commit()

    result = await session.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one()

    if user.role == "admin":
        from api.db import Run

        await session.execute(update(Run).where(Run.user_id.is_(None)).values(user_id=user.id))
        await session.commit()

    return user


async def get_or_create_user(
    sessionmaker: async_sessionmaker,
    *,
    google_sub: str,
    email: str,
    name: str | None,
    picture: str | None,
) -> User:
    """Look up a user by Google's stable `sub`, or create one.

    If a *second* login for the SAME google_sub races this one (e.g. a
    double-tab first login), the UNIQUE constraint on google_sub makes the
    loser's INSERT raise IntegrityError -- caught below, and handled by
    re-selecting and returning the winner's row rather than raising.
    """
    from api.db import User, utcnow

    email = email.strip().lower()

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

        try:
            return await _atomic_insert_user(
                session,
                google_sub=google_sub,
                email=email,
                name=name,
                picture=picture,
                password_hash=None,
                allow_admin_bootstrap=True,
            )
        except IntegrityError:
            await session.rollback()
            # Two distinct causes collapse to the same IntegrityError here,
            # both now real given users.email is UNIQUE too: (a) someone
            # else's INSERT for this exact google_sub won the race between
            # our "not found" lookup above and our own INSERT -- that row
            # is the real one now, re-select and return it; (b) this email
            # already belongs to a DIFFERENT account (e.g. a password
            # account registered first) -- google_sub genuinely has no
            # row, so re-selecting finds nothing, and creating a second
            # row silently or 500ing on the raw constraint violation are
            # both wrong. EmailAlreadyRegistered gives POST /auth/bootstrap
            # a clear, deliberate 409 for this instead of either.
            existing_after = await session.execute(select(User).where(User.google_sub == google_sub))
            user = existing_after.scalar_one_or_none()
            if user is not None:
                return user
            raise EmailAlreadyRegistered(email) from None


class EmailAlreadyRegistered(Exception):
    """Raised by create_password_user when the email is already taken --
    by a password account or a Google account, either way a second
    account for the same email is refused rather than silently linked
    (linking here would let anyone who merely knows a victim's email
    address register a password for it and share access to that Google
    account's data; a deliberate "add a password to my existing account"
    flow, from within an authenticated session, would be the safe way to
    offer linking later -- out of scope for this endpoint)."""


async def create_password_user(
    sessionmaker: async_sessionmaker,
    *,
    email: str,
    password: str,
    name: str | None,
) -> User:
    """Register a new password account. Raises EmailAlreadyRegistered if
    the email is already in use by any account (Google or password).

    Never eligible for admin (allow_admin_bootstrap=False, see
    _atomic_insert_user) -- this is an unauthenticated HTTP endpoint;
    completing Google's OAuth handshake is the only path that gets a
    real shot at the first-row-becomes-admin bootstrap.
    """
    from api.db import User, new_run_id

    email = email.strip().lower()
    password_hash = await hash_password_async(password)

    async with sessionmaker() as session:
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            raise EmailAlreadyRegistered(email)

        try:
            return await _atomic_insert_user(
                session,
                google_sub=f"local:{new_run_id()}",
                email=email,
                name=name,
                picture=None,
                password_hash=password_hash,
                allow_admin_bootstrap=False,
            )
        except IntegrityError as exc:
            # The synthetic google_sub is generated fresh above and cannot
            # collide (see api/db.py's User.google_sub comment) -- with
            # users.email now UNIQUE too, this can only mean a second
            # registration for the same email raced the "not found" check
            # above and won, or a Google account already owns this email.
            raise EmailAlreadyRegistered(email) from exc


async def authenticate_password_user(sessionmaker: async_sessionmaker, *, email: str, password: str) -> "User | None":
    """Verify email+password. Returns the user on success, None on any
    failure (no such email, no password set on that account, or wrong
    password) -- deliberately one outcome for the caller to branch on, the
    same anti-enumeration principle get_current_user's uniform 401
    already applies to bearer tokens."""
    from api.db import User, utcnow

    email = email.strip().lower()

    async with sessionmaker() as session:
        result = await session.execute(select(User).where(User.email == email))
        # .first(), not .scalar_one_or_none(): users.email is UNIQUE going
        # forward, but a row pair created before that constraint existed
        # (or a future migration gap) must never turn a login attempt into
        # an unhandled 500 -- which would itself be a distinguishable
        # signal ("this email is broken") on top of being a crash.
        user = result.scalars().first()

        if not await verify_password_async(password, user.password_hash if user else None):
            return None

        user.last_login_at = utcnow()
        # Cheap now, awkward to retrofit: if _password_hasher's cost
        # parameters are ever raised, existing accounts silently upgrade
        # on their next successful login instead of being stranded on the
        # old (weaker) parameters forever.
        if user.password_hash is not None and _password_hasher.check_needs_rehash(user.password_hash):
            user.password_hash = await hash_password_async(password)
        await session.commit()
        await session.refresh(user)
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
