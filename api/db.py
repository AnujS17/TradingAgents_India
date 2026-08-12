"""Database engine, session factory, and the Run table.

SQLite by default so the service runs with **zero installs** — no Docker, no
Postgres, no Redis. Everything here goes through SQLAlchemy, so moving to
Postgres later is a connection-string change plus a migration, not a rewrite.

Known limit, stated plainly: SQLite serialises writers. That is fine for a
prototype with one or two workers, and NOT fine for production concurrency —
switch to Postgres before real traffic. WAL mode below buys concurrent readers
alongside a single writer, which is the shape this service actually has (many
polling reads, occasional worker writes).
"""

from __future__ import annotations

import threading
from datetime import date as Date
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date as SADate,
    DateTime,
    Index,
    String,
    Text,
    event,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from api.settings import get_settings


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One analysis. Rows ACCUMULATE per (ticker, date, profile) — a forced
    re-run inserts a new row rather than replacing the old one, so results can
    be compared."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    analysis_date: Mapped[Date] = mapped_column(SADate)
    profile: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reports run to tens of thousands of words, so they live as JSON blobs
    # rather than columns. Nothing queries inside them.
    verdict: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reports: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Whether the worker should bypass the day's data snapshot. Set from the
    # request's refresh_data flag and read in the worker, so the intent
    # survives the hand-off through the queue.
    refresh_data: Mapped[bool] = mapped_column(Boolean, default=False)

    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (
        # The cache lookup: "has this exact question been answered?" Sorted by
        # created_at so "newest run for this question" is an index scan.
        Index("ix_runs_question", "ticker", "analysis_date", "profile", "created_at"),
        # The worker's claim query.
        Index("ix_runs_claim", "status", "created_at"),
    )


def _database_url() -> str:
    settings = get_settings()
    if settings.database_url:
        return settings.database_url
    # Sits beside the engine's own caches rather than in the repo, so a clone
    # is never polluted and the file survives a git clean.
    import os

    home = os.path.join(os.path.expanduser("~"), ".tradingagents")
    os.makedirs(home, exist_ok=True)
    return f"sqlite+aiosqlite:///{os.path.join(home, 'api.db')}"


_engine = None
_sessionmaker = None


def get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        url = _database_url()
        _engine = create_async_engine(url, future=True)
        if url.startswith("sqlite"):

            @event.listens_for(_engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _record):
                cursor = dbapi_connection.cursor()
                # WAL lets the API keep reading while a worker writes; without
                # it every poll can hit "database is locked" mid-run.
                cursor.execute("PRAGMA journal_mode=WAL")
                # Wait rather than failing instantly when the writer is busy.
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()

        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def create_tables() -> None:
    """Create the schema if absent.

    Adequate while the schema is still moving daily. Introduce Alembic before
    there is data worth preserving — this cannot alter an existing table.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_id_lock = threading.Lock()
_last_ns = 0


def new_run_id() -> str:
    """Time-ordered, strictly increasing run id. 32 chars, so the column is
    unchanged.

    Why not uuid4: it is fine for uniqueness but useless as a sort tiebreak,
    and ``created_at`` alone is not enough — two runs created back to back
    share a timestamp, after which "newest first" fell back to comparing
    random hex and returned them in arbitrary order. Users would have seen
    their run history reshuffle between page loads. Caught by two tests that
    failed roughly one run in three.

    Why not a bare ``time.time_ns()`` prefix either: that was the first
    attempt and it did NOT fix it. Windows' clock granularity is far coarser
    than a nanosecond, so several ids generated in a tight loop shared an
    identical prefix and the random tail decided the order again.

    Hence the counter below — if the clock has not advanced, step it forward
    by one. That guarantees a strict order within a process, while the real
    timestamp still orders ids across processes (the API and the worker).
    """
    import time
    import uuid

    global _last_ns
    with _id_lock:
        now = time.time_ns()
        if now <= _last_ns:
            now = _last_ns + 1
        _last_ns = now

    return f"{now:016x}{uuid.uuid4().hex[:16]}"
