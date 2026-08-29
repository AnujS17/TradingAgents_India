"""Every route in the app must require authentication unless explicitly
allow-listed as public. Enumerates api.main.create_app()'s own route
table rather than hand-listing endpoints -- a newly added, unprotected
route fails this suite automatically instead of needing a human to
remember to update a checklist here."""

import pytest
from fastapi.testclient import TestClient

from api.dependencies import InMemoryRunStore, get_run_store
from api.main import create_app

PUBLIC_PATHS = {
    "/health",
    "/push/vapid-public-key",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
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


@pytest.mark.unit
def test_every_non_public_route_requires_authentication():
    app = create_app()
    app.dependency_overrides[get_run_store] = lambda: InMemoryRunStore()

    protected_get_paths = []
    flattened_routes = _flatten_routes(app.routes)

    for route in flattened_routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or methods is None or path in PUBLIC_PATHS:
            continue
        if "{" in path:
            continue  # path-param routes checked individually below
        if "GET" in methods:
            protected_get_paths.append(path)

    assert "/runs" in protected_get_paths, "sanity check: the enumeration itself must find at least /runs"

    with TestClient(app) as client:
        for path in protected_get_paths:
            resp = client.get(path)
            assert resp.status_code == 401, f"{path} did not require authentication (got {resp.status_code})"


@pytest.mark.unit
def test_per_run_routes_require_authentication():
    """The {run_id}/{ticker}/{date} routes are excluded from the
    enumeration above (their real paths need a value substituted), so they
    get their own explicit check with a placeholder id/ticker/date --
    401 must come from the auth dependency, before the ID is ever looked
    up, so a placeholder that resolves to nothing is fine here."""
    app = create_app()
    app.dependency_overrides[get_run_store] = lambda: InMemoryRunStore()

    with TestClient(app) as client:
        for method, path in [
            ("get", "/runs/does-not-exist"),
            ("get", "/runs/does-not-exist/stream"),
            ("get", "/runs/does-not-exist/export.pdf"),
            ("get", "/runs/does-not-exist/export.xlsx"),
            ("post", "/runs/does-not-exist/stop"),
            ("post", "/runs/does-not-exist/resume"),
            ("post", "/runs/does-not-exist/subscribe"),
            ("get", "/runs/SIEMENS.NS/2026-08-26"),
            ("get", "/runs/SIEMENS.NS/2026-08-26/history"),
        ]:
            if method == "post":
                resp = getattr(client, method)(path, json={})
            else:
                resp = getattr(client, method)(path)
            assert resp.status_code == 401, f"{method.upper()} {path} did not require authentication (got {resp.status_code})"
