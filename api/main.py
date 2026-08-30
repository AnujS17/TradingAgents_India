"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routers import auth, health, runs
from api.settings import get_settings

# Fields whose raw value a 422 must never echo back. Pydantic's default
# validation-error handler includes the submitted `input` (and `ctx`) for
# every rejected field, on purpose, for debuggability -- fine for a
# ticker or a date, not for a password: an over-short or oversized
# password submitted to POST /auth/register comes back in the response
# body verbatim otherwise (verified directly), which routinely ends up in
# error-tracking services, API gateway logs, or a debug proxy's capture,
# none of which should ever hold a real plaintext credential.
_REDACT_FIELD_NAMES = {"password"}

DESCRIPTION = """
Multi-agent equity research for Indian markets (NSE/BSE).

**Analysis is asynchronous.** A run takes roughly 4 minutes (fast profile) to
14 minutes (detailed), so `POST /analyze` queues a job and returns an id to
poll. Repeat requests for the same ticker and date are served from the
existing run rather than spending a new one.

This is a research tool. It surfaces evidence, the bull and bear cases, and
the data behind them — it is not investment advice.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fine while the schema still moves daily. Introduce Alembic before there
    # is data worth preserving — create_all cannot alter an existing table.
    from api.db import create_tables

    await create_tables()
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=settings.allowed_methods,
        allow_headers=settings.allowed_headers,
    )

    @app.exception_handler(RequestValidationError)
    async def _redacted_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for error in exc.errors():
            if any(str(part) in _REDACT_FIELD_NAMES for part in error.get("loc", ())):
                error = {**error, "input": "[redacted]"}
                error.pop("ctx", None)
            errors.append(error)
        # jsonable_encoder, same as FastAPI's own default handler -- some
        # error entries carry non-JSON-native values (e.g. a ValueError in
        # ctx) that json.dumps would choke on directly.
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": jsonable_encoder(errors)})

    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(runs.router)

    return app


app = create_app()
