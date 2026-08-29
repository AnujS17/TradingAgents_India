"""users table: schema, uniqueness, and the role/tier defaults new accounts get."""

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import Base, User


@pytest.fixture
def sessionmaker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
def test_a_new_user_defaults_to_role_user_and_tier_free(sessionmaker):
    async def scenario():
        async with sessionmaker() as session:
            user = User(
                id="u1",
                google_sub="sub-123",
                email="a@example.com",
                created_at=datetime.now(timezone.utc),
            )
            session.add(user)
            await session.commit()
            return await session.get(User, "u1")

    user = _run(scenario())
    assert user.role == "user"
    assert user.tier == "free"


@pytest.mark.unit
def test_google_sub_must_be_unique(sessionmaker):
    async def scenario():
        async with sessionmaker() as session:
            session.add(User(id="u1", google_sub="dup", email="a@x.com", created_at=datetime.now(timezone.utc)))
            await session.commit()
            session.add(User(id="u2", google_sub="dup", email="b@x.com", created_at=datetime.now(timezone.utc)))
            await session.commit()

    with pytest.raises(IntegrityError):
        _run(scenario())
