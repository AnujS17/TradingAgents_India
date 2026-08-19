"""Database-backed RunStore, plus the worker's job-claim query.

There is no separate queue service. The ``runs`` table *is* the queue: rows
land as ``queued`` and a worker claims the oldest one atomically. That removes
Redis from the prototype's dependencies, and the claim is written so it stays
correct if a second worker is started.

Swapping in Redis/RQ later means replacing ``claim_next_run`` and the worker
loop — the store and every HTTP handler stay as they are.
"""

from __future__ import annotations

from datetime import date as Date

from sqlalchemy import select, update

from api.db import Run, get_sessionmaker, new_run_id, utcnow
from api.news_sources import extract_news_sources
from api.schemas import (
    AnalysisProfile,
    Reports,
    RunDetail,
    RunHistory,
    RunStatus,
    RunSummary,
    Verdict,
)


def _to_detail(row: Run) -> RunDetail:
    reports = Reports.model_validate(row.reports) if row.reports else None
    return RunDetail(
        id=row.id,
        ticker=row.ticker,
        analysis_date=row.analysis_date,
        profile=AnalysisProfile(row.profile),
        status=RunStatus(row.status),
        created_at=row.created_at,
        completed_at=row.completed_at,
        error=row.error,
        verdict=Verdict.model_validate(row.verdict) if row.verdict else None,
        reports=reports,
        news_sources=extract_news_sources(reports) if reports else [],
    )


def _ratings(rows: list[Run]) -> list[str | None]:
    return [
        (row.verdict or {}).get("rating")
        for row in rows
        if row.status == RunStatus.COMPLETED.value
    ]


def _contested(rows: list[Run]) -> bool:
    """Did repeat runs of the identical question reach different ratings?

    Surfaced rather than hidden: the day's inputs are snapshotted, so two runs
    read the SAME data and a split means the evidence is genuinely balanced.
    """
    distinct = {r for r in _ratings(rows) if r}
    return len(distinct) > 1


class SqlRunStore:
    """RunStore backed by the database. Satisfies the same Protocol the
    in-memory store does, so no HTTP handler changes."""

    def __init__(self, sessionmaker=None) -> None:
        self._sessionmaker = sessionmaker or get_sessionmaker()

    async def _siblings(
        self, session, ticker: str, analysis_date: Date, profile: AnalysisProfile
    ) -> list[Run]:
        """Every non-failed run for one question, newest first.

        Failed runs are excluded everywhere: one transient vendor outage must
        not poison a ticker for the rest of the day, nor inflate the run count
        a user sees.
        """
        result = await session.execute(
            select(Run)
            .where(
                Run.ticker == ticker,
                Run.analysis_date == analysis_date,
                Run.profile == profile.value,
                Run.status != RunStatus.FAILED.value,
            )
            .order_by(Run.created_at.desc(), Run.id.desc())
        )
        return list(result.scalars())

    async def create(
        self,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        refresh_data: bool = False,
        requested_by: str | None = None,
    ) -> RunDetail:
        async with self._sessionmaker() as session:
            row = Run(
                id=new_run_id(),
                ticker=ticker,
                analysis_date=analysis_date,
                profile=profile.value,
                status=RunStatus.QUEUED.value,
                created_at=utcnow(),
                refresh_data=refresh_data,
                requested_by=requested_by,
            )
            session.add(row)
            await session.commit()
            return _to_detail(row)

    async def get(self, run_id: str) -> RunDetail | None:
        async with self._sessionmaker() as session:
            row = await session.get(Run, run_id)
            if row is None:
                return None
            siblings = await self._siblings(
                session, row.ticker, row.analysis_date, AnalysisProfile(row.profile)
            )
            return _to_detail(row).model_copy(
                update={
                    "run_count": len(siblings),
                    "verdict_is_contested": _contested(siblings),
                }
            )

    async def find(
        self, ticker: str, analysis_date: Date, profile: AnalysisProfile
    ) -> RunDetail | None:
        """Newest usable run, preferring a finished one — a caller asking this
        question wants an answer now, and an in-flight run surfaces later."""
        async with self._sessionmaker() as session:
            siblings = await self._siblings(session, ticker, analysis_date, profile)
            if not siblings:
                return None
            completed = [r for r in siblings if r.status == RunStatus.COMPLETED.value]
            chosen = completed[0] if completed else siblings[0]
            return _to_detail(chosen).model_copy(
                update={
                    "cached": True,
                    "run_count": len(siblings),
                    "verdict_is_contested": _contested(siblings),
                }
            )

    async def history(
        self, ticker: str, analysis_date: Date, profile: AnalysisProfile
    ) -> RunHistory | None:
        async with self._sessionmaker() as session:
            siblings = await self._siblings(session, ticker, analysis_date, profile)
            if not siblings:
                return None
            return RunHistory(
                ticker=ticker,
                analysis_date=analysis_date,
                profile=profile,
                run_count=len(siblings),
                ratings=_ratings(siblings),
                verdict_is_contested=_contested(siblings),
                runs=[
                    RunSummary.model_validate(r, from_attributes=True)
                    for r in siblings
                ],
            )

    async def list(
        self, ticker: str | None, limit: int, offset: int
    ) -> list[RunSummary]:
        async with self._sessionmaker() as session:
            stmt = select(Run)
            if ticker is not None:
                stmt = stmt.where(Run.ticker == ticker)
            # id as tiebreak so pagination is deterministic when timestamps
            # collide.
            stmt = stmt.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit).offset(offset)
            rows = list((await session.execute(stmt)).scalars())
            return [
                RunSummary.model_validate(r, from_attributes=True) for r in rows
            ]

    # --- worker-side ---------------------------------------------------

    async def claim_next_run(self) -> Run | None:
        """Atomically take the oldest queued run and mark it running.

        The UPDATE is conditional on the row STILL being queued, so if two
        workers race for the same id exactly one wins — the loser's update
        matches zero rows and it simply tries again. Doing this as
        select-then-update without the condition would hand the same job to
        both, and a duplicated run costs a full analysis.
        """
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Run)
                .where(Run.status == RunStatus.QUEUED.value)
                .order_by(Run.created_at)
                .limit(1)
            )
            candidate = result.scalar_one_or_none()
            if candidate is None:
                return None

            claimed = await session.execute(
                update(Run)
                .where(Run.id == candidate.id, Run.status == RunStatus.QUEUED.value)
                .values(status=RunStatus.RUNNING.value, started_at=utcnow())
            )
            await session.commit()

            if claimed.rowcount == 0:
                return None  # lost the race; caller polls again

            await session.refresh(candidate)
            return candidate

    async def mark_completed(
        self, run_id: str, verdict: Verdict, reports: Reports
    ) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status=RunStatus.COMPLETED.value,
                    completed_at=utcnow(),
                    verdict=verdict.model_dump(),
                    reports=reports.model_dump(),
                )
            )
            await session.commit()

    async def mark_failed(self, run_id: str, error: str) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status=RunStatus.FAILED.value,
                    completed_at=utcnow(),
                    # Truncated: a traceback can be enormous, and this is shown
                    # to users.
                    error=error[:2000],
                )
            )
            await session.commit()

    async def count_runs_today(self, requested_by: str | None = None) -> int:
        """Spend counter for the rate limiter. Counts every run including
        failures — a failed run still cost LLM calls."""
        from datetime import timedelta

        since = utcnow() - timedelta(days=1)
        async with self._sessionmaker() as session:
            from sqlalchemy import func

            stmt = select(func.count(Run.id)).where(Run.created_at >= since)
            if requested_by is not None:
                stmt = stmt.where(Run.requested_by == requested_by)
            return (await session.execute(stmt)).scalar_one()
