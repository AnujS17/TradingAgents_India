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

from sqlalchemy import delete, select, update

from api.db import Run, RunEvent, get_sessionmaker, new_run_id, utcnow
from api.news_sources import extract_news_sources
from api.schemas import (
    AnalysisProfile,
    Reports,
    RunDetail,
    RunEventOut,
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
        requested_time_horizon=row.requested_time_horizon,
        user_id=row.user_id,
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
        self,
        session,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        owner: str | None = None,
    ) -> list[Run]:
        """Every completed-or-in-flight run for one question, newest first.

        Failed and cancelled runs are excluded everywhere: neither produced
        a real answer, so neither should inflate the run count a user sees
        or poison a ticker's comparison history for the rest of the day.

        ``owner`` defaults to ``None`` (no filter) so ``get``'s existing
        call site -- which has already fetched one specific row by id and
        leaves access control to the router -- keeps working unchanged.
        """
        stmt = select(Run).where(
            Run.ticker == ticker,
            Run.analysis_date == analysis_date,
            Run.profile == profile.value,
            Run.status.not_in([RunStatus.FAILED.value, RunStatus.CANCELLED.value]),
        )
        if owner is not None:
            stmt = stmt.where(Run.user_id == owner)
        result = await session.execute(stmt.order_by(Run.created_at.desc(), Run.id.desc()))
        return list(result.scalars())

    async def create(
        self,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        refresh_data: bool = False,
        requested_by: str | None = None,
        time_horizon: str | None = None,
        resume: bool = False,
        owner: str | None = None,
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
                requested_time_horizon=time_horizon,
                resume=resume,
                user_id=owner,
            )
            session.add(row)
            await session.commit()
            return _to_detail(row)

    async def create_resume(
        self, run_id: str, requested_by: str | None = None
    ) -> RunDetail | None:
        """Queue a new run that continues a failed one instead of starting
        fresh -- same ticker, date, profile, refresh_data and time horizon
        as the original, plus resume=True so the worker lets the engine pick
        up whatever checkpoint the failed attempt left behind.

        Returns None when there is nothing to resume: no such run, or the
        run hasn't reached ``failed`` (a queued/running run has nothing to
        continue from yet; a completed/cancelled run doesn't need to).
        Whether a checkpoint actually exists is NOT checked here -- the
        engine's own resume logic already degrades gracefully to a fresh
        start if there is nothing to pick up, so this only needs to gate on
        "does it make sense to ask," not "will there be anything to resume."
        """
        async with self._sessionmaker() as session:
            original = await session.get(Run, run_id)
            if original is None or original.status != RunStatus.FAILED.value:
                return None

            row = Run(
                id=new_run_id(),
                ticker=original.ticker,
                analysis_date=original.analysis_date,
                profile=original.profile,
                status=RunStatus.QUEUED.value,
                created_at=utcnow(),
                refresh_data=original.refresh_data,
                requested_by=requested_by,
                requested_time_horizon=original.requested_time_horizon,
                resume=True,
                user_id=original.user_id,
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
        self,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        owner: str | None,
        bypass_owner_check: bool = False,
    ) -> RunDetail | None:
        """Newest usable run, preferring a finished one — a caller asking this
        question wants an answer now, and an in-flight run surfaces later.

        ``bypass_owner_check`` is the admin escape hatch, and it is
        deliberately a separate parameter rather than overloading ``owner``
        with a second meaning: ``owner=None`` on its own still means "match
        only unclaimed rows" (the Task 5 fix), never "everyone's runs" --
        only ``bypass_owner_check=True`` skips the filter entirely.
        """
        async with self._sessionmaker() as session:
            siblings = await self._siblings(session, ticker, analysis_date, profile)
            if not bypass_owner_check:
                siblings = [r for r in siblings if r.user_id == owner]
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
        self,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        owner: str | None,
        bypass_owner_check: bool = False,
    ) -> RunHistory | None:
        async with self._sessionmaker() as session:
            siblings = await self._siblings(session, ticker, analysis_date, profile)
            if not bypass_owner_check:
                siblings = [r for r in siblings if r.user_id == owner]
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
        self, ticker: str | None, limit: int, offset: int, owner: str | None
    ) -> list[RunSummary]:
        async with self._sessionmaker() as session:
            stmt = select(Run)
            if ticker is not None:
                stmt = stmt.where(Run.ticker == ticker)
            if owner is not None:
                stmt = stmt.where(Run.user_id == owner)
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
        callers race for the same id exactly one wins — the loser's update
        matches zero rows. That loser retries against the next-oldest
        candidate in the SAME call rather than returning None: with only one
        worker lane this loop never repeats, but with several lanes racing
        concurrently (see api/worker.py's worker_lane), a bare loss must not
        be reported the same way as "queue empty" — the caller's response to
        None is a multi-second poll sleep, which would leave a lane dormant
        while a different row is still sitting there queued.
        """
        async with self._sessionmaker() as session:
            while True:
                result = await session.execute(
                    select(Run)
                    .where(Run.status == RunStatus.QUEUED.value)
                    .order_by(Run.created_at)
                    .limit(1)
                )
                candidate = result.scalar_one_or_none()
                if candidate is None:
                    return None  # genuinely nothing queued

                claimed = await session.execute(
                    update(Run)
                    .where(Run.id == candidate.id, Run.status == RunStatus.QUEUED.value)
                    .values(status=RunStatus.RUNNING.value, started_at=utcnow())
                )
                await session.commit()

                if claimed.rowcount == 0:
                    continue  # lost the race; try the next-oldest candidate

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
            # run_events is ephemeral -- the terminal state above is the
            # permanent record, so the streamed chunks that built it are no
            # longer needed. Deleted in the same transaction as the status
            # update so a crash between the two can never orphan events.
            await session.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
            await session.commit()

    async def request_stop(self, run_id: str) -> RunDetail | None:
        """Ask a queued or running analysis to stop.

        A queued run (never claimed by a worker) is cancelled directly --
        nothing is executing yet to cooperatively check a flag. A running
        run gets stop_requested=True; the worker picks it up via
        RunEventWriter.should_stop(), polled once per streamed chunk in
        propagate_streaming (api/streaming.py, tradingagents/graph/
        trading_graph.py) -- cooperative, typically within about one
        token's latency, not instant.

        Returns the updated row, or None if the run doesn't exist or has
        already reached a terminal state (nothing left to stop).
        """
        async with self._sessionmaker() as session:
            row = await session.get(Run, run_id)
            if row is None:
                return None

            if row.status == RunStatus.QUEUED.value:
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id, Run.status == RunStatus.QUEUED.value)
                    .values(status=RunStatus.CANCELLED.value, completed_at=utcnow())
                )
            elif row.status == RunStatus.RUNNING.value:
                await session.execute(
                    update(Run).where(Run.id == run_id).values(stop_requested=True)
                )
            else:
                return None  # already completed/failed/cancelled -- nothing to stop

            await session.commit()
            await session.refresh(row)
            return _to_detail(row)

    async def mark_cancelled(self, run_id: str) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(status=RunStatus.CANCELLED.value, completed_at=utcnow())
            )
            await session.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
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
            await session.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
            await session.commit()

    # --- streaming -------------------------------------------------------

    async def get_events_since(self, run_id: str, after_seq: int) -> list[RunEventOut]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                .order_by(RunEvent.seq)
            )
            return [
                RunEventOut(seq=row.seq, node_name=row.node_name, text_delta=row.text_delta)
                for row in result.scalars()
            ]

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
