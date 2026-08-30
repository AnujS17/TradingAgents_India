"""Every route in the app must require authentication unless explicitly
allow-listed as public. Enumerates api.main.create_app()'s own route
table rather than hand-listing endpoints -- a newly added, unprotected
route fails this suite automatically instead of needing a human to
remember to update a checklist here.

Covers every HTTP method (not just GET) and every path, including those
with path parameters (a placeholder value is substituted per parameter
name). A route requiring a body (POST) is sent an empty JSON object --
the auth dependency must reject before FastAPI ever validates the body,
so a 401 is expected regardless of what a real body would need to look
like; if this ever regresses to a 422 (body validated first), that is
itself a bug this test will now catch.
"""

import re

import pytest
from fastapi.testclient import TestClient

from api.dependencies import InMemoryRunStore, get_run_store
from api.main import create_app

PUBLIC_PATHS = {
    # Genuinely public, unlike /auth/bootstrap: a caller has no token yet
    # by definition when hitting either of these, that is the whole point
    # of them. Each has its own dedicated auth-failure tests
    # (tests/test_auth_password.py) -- wrong credentials, rate limiting,
    # duplicate email -- this generic gate isn't the right place for that.
    "/auth/register",
    "/auth/login",
    "/health",
    "/push/vapid-public-key",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

# One placeholder value per path-parameter name used anywhere in the route
# table. A 401 must come from the auth dependency before the value is ever
# looked up, so these don't need to resolve to anything real -- but
# analysis_date is typed as a date, so it must at least be a valid date
# string or FastAPI's own path-param validation would 422 before auth ever
# runs, which would defeat the point of this test.
PATH_PARAM_PLACEHOLDERS = {
    "run_id": "does-not-exist",
    "ticker": "SIEMENS.NS",
    "analysis_date": "2026-08-26",
}


def _flatten_routes(routes):
    """Recursively flatten routes, unwrapping nested _IncludedRouter objects.

    Ensures that even deeply nested routers (routers included in other routers
    before mounting on the app) are enumerated, preventing unprotected routes
    from silently slipping through if the app structure changes.
    """
    flat = []
    for route in routes:
        if hasattr(route, "original_router"):
            flat.extend(_flatten_routes(route.original_router.routes))
        else:
            flat.append(route)
    return flat


def _fill_path_params(path: str) -> str:
    def _sub(match: re.Match) -> str:
        name = match.group(1)
        if name not in PATH_PARAM_PLACEHOLDERS:
            raise KeyError(
                f"route path {path!r} uses a path parameter {name!r} with no "
                f"placeholder registered in PATH_PARAM_PLACEHOLDERS -- add one "
                f"rather than letting this route silently skip coverage"
            )
        return PATH_PARAM_PLACEHOLDERS[name]

    return re.sub(r"\{([^}]+)\}", _sub, path)


def _enumerate_protected_requests() -> list[tuple[str, str]]:
    """Every (method, concrete-path) pair in the live route table that
    isn't explicitly public. Any HTTP method, any path shape."""
    app = create_app()
    requests: list[tuple[str, str]] = []
    for route in _flatten_routes(app.routes):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or methods is None or path in PUBLIC_PATHS:
            continue
        concrete_path = _fill_path_params(path)
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            requests.append((method, concrete_path))
    return requests


@pytest.mark.unit
def test_every_non_public_route_requires_authentication():
    protected = _enumerate_protected_requests()
    assert ("GET", "/runs") in protected, "sanity check: the enumeration itself must find /runs"
    assert ("POST", "/analyze") in protected, "sanity check: the enumeration must cover non-GET, non-path-param routes too"

    app = create_app()
    app.dependency_overrides[get_run_store] = lambda: InMemoryRunStore()

    with TestClient(app) as client:
        for method, path in protected:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.request(method, path, json={})
            assert resp.status_code == 401, f"{method} {path} did not require authentication (got {resp.status_code})"
