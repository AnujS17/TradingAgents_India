"""runs.user_id: the guarded ALTER TABLE that lets an existing (pre-auth)
database gain the column without a full migration tool, mirroring the
pattern already used for stop_requested/requested_time_horizon/resume."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.db import create_tables
from api.settings import get_settings


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("TRADINGAGENTS_API_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    import api.db as db_module

    db_module._engine = None
    db_module._sessionmaker = None
    yield
    db_module._engine = None
    db_module._sessionmaker = None
    get_settings.cache_clear()


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
def test_a_pre_auth_runs_table_gains_a_nullable_user_id_column(tmp_path):
    """Simulates upgrading an existing database: create the OLD schema
    (no user_id) directly, then run create_tables() and confirm the column
    appears without touching existing rows."""
    from api.db import get_engine

    async def scenario():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE runs (id VARCHAR(32) PRIMARY KEY, ticker VARCHAR(32), "
                "status VARCHAR(16), created_at TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO runs (id, ticker, status, created_at) VALUES "
                "('r1', 'SIEMENS.NS', 'completed', '2026-08-01 00:00:00')"
            ))
            await conn.commit()

        await create_tables()

        async with engine.begin() as conn:
            result = await conn.execute(text("PRAGMA table_info(runs)"))
            columns = {row[1] for row in result.fetchall()}
            row = (await conn.execute(text("SELECT user_id FROM runs WHERE id = 'r1'"))).fetchone()

        return columns, row[0]

    columns, user_id = _run(scenario())
    assert "user_id" in columns
    assert user_id is None
