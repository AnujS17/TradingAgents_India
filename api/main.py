"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health, runs
from api.settings import get_settings

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

    app.include_router(health.router)
    app.include_router(runs.router)

    return app


app = create_app()
