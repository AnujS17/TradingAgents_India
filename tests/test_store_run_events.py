"""Guard for RunStore's run_events read + deletion-on-completion wiring."""

import asyncio
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import Base, RunEvent
from api.schemas import AnalysisProfile, Reports, Verdict
from api.store import SqlRunStore


@pytest.fixture
def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield SqlRunStore(sessionmaker=maker)
    asyncio.run(engine.dispose())


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
def test_get_events_since_returns_only_newer_events(store):
    async def scenario():
        created = await store.create("EXAMPLE.NS", date(2026, 8, 1), AnalysisProfile.FAST)
        async with store._sessionmaker() as session:
            session.add_all([
                RunEvent(run_id=created.id, seq=1, node_name="a", text_delta="x", created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
                RunEvent(run_id=created.id, seq=2, node_name="a", text_delta="y", created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
            ])
            await session.commit()
        return await store.get_events_since(created.id, after_seq=1)

    events = _run(scenario())
    assert len(events) == 1
    assert events[0].seq == 2
    assert events[0].text_delta == "y"


@pytest.mark.unit
def test_mark_completed_deletes_that_runs_events(store):
    async def scenario():
        created = await store.create("EXAMPLE.NS", date(2026, 8, 1), AnalysisProfile.FAST)
        async with store._sessionmaker() as session:
            session.add(RunEvent(run_id=created.id, seq=1, node_name="a", text_delta="x", created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
            await session.commit()

        await store.mark_completed(created.id, Verdict(), Reports())
        return await store.get_events_since(created.id, after_seq=0)

    assert _run(scenario()) == []


@pytest.mark.unit
def test_mark_failed_deletes_that_runs_events(store):
    async def scenario():
        created = await store.create("EXAMPLE.NS", date(2026, 8, 1), AnalysisProfile.FAST)
        async with store._sessionmaker() as session:
            session.add(RunEvent(run_id=created.id, seq=1, node_name="a", text_delta="x", created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
            await session.commit()

        await store.mark_failed(created.id, "boom")
        return await store.get_events_since(created.id, after_seq=0)

    assert _run(scenario()) == []
