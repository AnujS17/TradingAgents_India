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


@pytest.mark.unit
def test_find_with_owner_none_never_returns_another_users_run(sql_store):
    """The gap this regression test exists for: owner=None must not mean
    'no filter' for find/history -- only list's admin path gets that
    bypass. A caller passing owner=None should see nothing but genuinely
    unclaimed (user_id IS NULL) runs, never someone else's."""
    async def scenario():
        await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
        return await sql_store.find("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner=None)

    assert _run(scenario()) is None


@pytest.mark.unit
def test_history_with_owner_none_never_returns_another_users_run(sql_store):
    async def scenario():
        await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
        return await sql_store.history("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner=None)

    history = _run(scenario())

    assert history is None


# --- bypass_owner_check (the admin escape hatch) --------------------------
#
# owner=None alone must never mean "no filter" for find/history -- that's
# the regression the tests above guard. The admin path needs a DIFFERENT,
# structurally distinct way to see everyone's runs: bypass_owner_check=True.


@pytest.mark.unit
def test_find_bypass_owner_check_returns_another_users_run(sql_store):
    stores = [sql_store, InMemoryRunStore()]
    for store in stores:
        async def scenario(store=store):
            created = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
            found = await store.find(
                "SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="admin-1", bypass_owner_check=True
            )
            return created, found

        created, found = _run(scenario())
        assert found is not None, f"{type(store).__name__} bypass_owner_check did not bypass"
        assert found.id == created.id


@pytest.mark.unit
def test_history_bypass_owner_check_returns_another_users_run(sql_store):
    stores = [sql_store, InMemoryRunStore()]
    for store in stores:
        async def scenario(store=store):
            await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
            return await store.history(
                "SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="admin-1", bypass_owner_check=True
            )

        history = _run(scenario())
        assert history is not None, f"{type(store).__name__} bypass_owner_check did not bypass"
        assert history.run_count == 1


@pytest.mark.unit
def test_find_bypass_owner_check_false_by_default_still_scopes_to_owner(sql_store):
    """The default must stay exactly as strict as before this fix -- a
    caller that forgets to pass bypass_owner_check gets the safe behavior,
    not an accidental leak."""
    async def scenario():
        await sql_store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
        return await sql_store.find("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-b")

    assert _run(scenario()) is None


@pytest.mark.unit
def test_get_scopes_run_count_to_the_rows_own_owner():
    """get()'s run_count/verdict_is_contested must reflect only the row's
    own owner's history with this ticker/date/profile -- not every user's,
    which _siblings' unfiltered default would otherwise pull in (get()
    relies on that default for row-fetch access control, not for these
    aggregates)."""
    stores = [SqlRunStore, InMemoryRunStore]
    for store_cls in stores:
        store = store_cls() if store_cls is InMemoryRunStore else None

        async def scenario(store_cls=store_cls):
            if store_cls is SqlRunStore:
                import tempfile

                from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

                with tempfile.TemporaryDirectory() as d:
                    engine = create_async_engine(f"sqlite+aiosqlite:///{d}/test.db")
                    async with engine.begin() as conn:
                        await conn.run_sync(Base.metadata.create_all)
                    store = SqlRunStore(sessionmaker=async_sessionmaker(engine, expire_on_commit=False))
                    mine = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
                    await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-b")
                    await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-c")
                    fetched = await store.get(mine.id)
                    await engine.dispose()
                    return fetched
            else:
                store = InMemoryRunStore()
                mine = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
                await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-b")
                await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-c")
                return await store.get(mine.id)

        fetched = _run(scenario())
        assert fetched is not None
        assert fetched.run_count == 1, (
            f"{store_cls.__name__} leaked other users' runs into run_count "
            f"(got {fetched.run_count}, expected 1)"
        )


@pytest.mark.unit
def test_get_groups_unclaimed_legacy_runs_with_each_other_only():
    """A legacy run with user_id=None (predates the ownership migration)
    must only be grouped with OTHER unclaimed runs, never with a claimed
    one -- owner=None must mean strict-match-on-NULL here too, the same
    property Task 5 established for find/history."""
    stores = [SqlRunStore, InMemoryRunStore]
    for store_cls in stores:

        async def scenario(store_cls=store_cls):
            if store_cls is SqlRunStore:
                import tempfile

                from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

                with tempfile.TemporaryDirectory() as d:
                    engine = create_async_engine(f"sqlite+aiosqlite:///{d}/test.db")
                    async with engine.begin() as conn:
                        await conn.run_sync(Base.metadata.create_all)
                    store = SqlRunStore(sessionmaker=async_sessionmaker(engine, expire_on_commit=False))
                    legacy = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner=None)
                    await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
                    fetched = await store.get(legacy.id)
                    await engine.dispose()
                    return fetched
            else:
                store = InMemoryRunStore()
                legacy = await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner=None)
                await store.create("SIEMENS.NS", DAY, AnalysisProfile.FAST, owner="user-a")
                return await store.get(legacy.id)

        fetched = _run(scenario())
        assert fetched is not None
        assert fetched.run_count == 1, (
            f"{store_cls.__name__} grouped a claimed run with an unclaimed one "
            f"(got run_count={fetched.run_count}, expected 1)"
        )
