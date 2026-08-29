"""Ownership scoping at the store layer: find/list/history must never
return one user's run to a different user's query -- this is the actual
privacy boundary, independent of whatever the HTTP layer does on top."""

import asyncio
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import Base
from api.dependencies import InMemoryRunStore
from api.schemas import AnalysisProfile
from api.store import SqlRunStore

DAY = date(2026, 8, 26)


@pytest.fixture
def sql_store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield SqlRunStore(sessionmaker=async_sessionmaker(engine, expire_on_commit=False))
    asyncio.run(engine.dispose())


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
def test_find_never_returns_a_different_users_run(sql_store, tmp_path):
    stores = [sql_store, InMemoryRunStore()]
    for store in stores:
        async def scenario(store=store):
            await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
            return await store.find("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-b")

        assert _run(scenario()) is None, f"{type(store).__name__} leaked across owners"


@pytest.mark.unit
def test_find_returns_the_owners_own_run(sql_store):
    async def scenario():
        created = await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
        return created, await sql_store.find("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")

    created, found = _run(scenario())
    assert found is not None
    assert found.id == created.id


@pytest.mark.unit
def test_list_only_returns_the_owners_runs(sql_store):
    async def scenario():
        await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
        await sql_store.create("HAL.NS", DAY, AnalysisProfile.FAST, owner="user-b")
        return await sql_store.list(ticker=None, limit=20, offset=0, owner="user-a")

    results = _run(scenario())
    assert len(results) == 1
    assert results[0].ticker == "SIEMENS.NS"


@pytest.mark.unit
def test_list_with_owner_none_returns_everyone_runs_admin_path(sql_store):
    async def scenario():
        await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
        await sql_store.create("HAL.NS", DAY, AnalysisProfile.FAST, owner="user-b")
        return await sql_store.list(ticker=None, limit=20, offset=0, owner=None)

    results = _run(scenario())
    assert len(results) == 2


@pytest.mark.unit
def test_history_is_scoped_to_the_owner_too(sql_store):
    async def scenario():
        await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
        await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-b")
        return await sql_store.history("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")

    history = _run(scenario())
    assert history.run_count == 1
