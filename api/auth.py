"""JWT verification for the API's half of the auth split.

NextAuth (the Next.js frontend) issues the token; this module only ever
verifies one, never issues one -- FastAPI has no login endpoint. See
docs/superpowers/specs/2026-08-29-auth-rbac-design.md for the full
architecture.
"""

from __future__ import annotations

import jwt

from api.settings import get_settings


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
