"""Shared FastAPI dependencies.

The run store is defined as a Protocol with an in-memory implementation. That
is deliberate scaffolding, not laziness: the routers are written against the
interface now, so introducing Postgres and RQ in the next step is a change to
this file and a new implementation — not a rewrite of every handler.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime, timezone
from typing import Annotated, Protocol

from fastapi import Depends

from api.db import PushSubscription, new_run_id
from api.schemas import (
    AnalysisProfile,
    RunDetail,
    RunEventOut,
    RunHistory,
    RunStatus,
    RunSummary,
)


class RunStore(Protocol):
    """Persistence boundary for analysis runs.

    Runs ACCUMULATE per (ticker, date, profile) rather than overwriting: a user
    who asks for a fresh analysis gets a new run alongside the old one, so the
    two can be compared. ``find`` returns the newest usable one.
    """

    async def create(
        self,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        refresh_data: bool = False,
        requested_by: str | None = None,
        time_horizon: str | None = None,
        owner: str | None = None,
    ) -> RunDetail: ...

    async def create_resume(
        self, run_id: str, requested_by: str | None = None
    ) -> RunDetail | None: ...

    async def get(self, run_id: str) -> RunDetail | None: ...

    async def find(
        self,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        owner: str | None,
        bypass_owner_check: bool = False,
    ) -> RunDetail | None: ...

    async def history(
        self,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        owner: str | None,
        bypass_owner_check: bool = False,
    ) -> RunHistory | None: ...

    async def count_runs_today(self, requested_by: str | None = None) -> int: ...

    async def list(
        self, ticker: str | None, limit: int, offset: int, owner: str | None
    ) -> list[RunSummary]: ...

    async def request_stop(self, run_id: str) -> RunDetail | None: ...

    async def get_events_since(self, run_id: str, after_seq: int) -> list[RunEventOut]: ...

    async def add_push_subscription(
        self, run_id: str, endpoint: str, p256dh: str, auth: str
    ) -> None: ...

    async def get_push_subscriptions(self, run_id: str) -> list[PushSubscription]: ...

    async def clear_push_subscriptions(self, run_id: str) -> None: ...


def _rating_of(run: RunDetail) -> str | None:
    return run.verdict.rating if run.verdict is not None else None


class InMemoryRunStore:
    """Process-local store. Development and tests only.

    Everything vanishes on restart and nothing is shared between workers, so
    this must be replaced before anything real runs against it. It exists so
    the HTTP surface can be exercised end to end before Postgres is stood up.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunDetail] = {}
        self._push_subscriptions: dict[str, list[PushSubscription]] = {}

    @staticmethod
    def _key(ticker: str, analysis_date: Date, profile: AnalysisProfile) -> str:
        return f"{ticker}|{analysis_date.isoformat()}|{profile.value}"

    def _siblings(
        self, ticker: str, analysis_date: Date, profile: AnalysisProfile
    ) -> list[RunDetail]:
        """Every completed-or-in-flight run for one question, newest first.

        Failed and cancelled runs are excluded throughout: neither produced a
        real answer, so neither should count toward the run total a user
        sees or poison a ticker's comparison history for the rest of the day.
        """
        target = self._key(ticker, analysis_date, profile)
        matches = [
            run
            for run in self._runs.values()
            if self._key(run.ticker, run.analysis_date, run.profile) == target
            and run.status not in (RunStatus.FAILED, RunStatus.CANCELLED)
        ]
        matches.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        return matches

    @staticmethod
    def _contested(runs: list[RunDetail]) -> bool:
        """Did repeat runs of the identical question reach different ratings?

        Worth surfacing rather than hiding. The day's data is snapshotted, so
        two runs read the SAME inputs — a disagreement is the model telling you
        the evidence is genuinely balanced. Observed on SIEMENS.NS: Hold and
        Sell/Underweight on the same day and data.
        """
        ratings = {_rating_of(r) for r in runs if r.status is RunStatus.COMPLETED}
        ratings.discard(None)
        return len(ratings) > 1

    async def create(
        self,
        ticker: str,
        analysis_date: Date,
        profile: AnalysisProfile,
        refresh_data: bool = False,
        requested_by: str | None = None,
        time_horizon: str | None = None,
        owner: str | None = None,
    ) -> RunDetail:
        run = RunDetail(
            id=new_run_id(),
            ticker=ticker,
            analysis_date=analysis_date,
            profile=profile,
            status=RunStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
            requested_time_horizon=time_horizon,
            user_id=owner,
        )
        self._runs[run.id] = run
        return run

    async def create_resume(
        self, run_id: str, requested_by: str | None = None
    ) -> RunDetail | None:
        original = self._runs.get(run_id)
        if original is None or original.status is not RunStatus.FAILED:
            return None
        run = RunDetail(
            id=new_run_id(),
            ticker=original.ticker,
            analysis_date=original.analysis_date,
            profile=original.profile,
            status=RunStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
            requested_time_horizon=original.requested_time_horizon,
            user_id=original.user_id,
        )
        self._runs[run.id] = run
        return run

    async def get(self, run_id: str) -> RunDetail | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        # Scoped to the row's OWN owner, not left unfiltered. Unfiltered
        # siblings would count every user's runs of this ticker/date/profile
        # into run_count and let a stranger's rating flip
        # verdict_is_contested -- the aggregates on a run's own detail page
        # must reflect only that run owner's history with the same
        # question, matching find/history's owner-scoping below. `None ==
        # None` here correctly groups a legacy unclaimed run only with
        # other unclaimed runs, never with anyone's claimed ones.
        siblings = [
            r
            for r in self._siblings(run.ticker, run.analysis_date, run.profile)
            if getattr(r, "user_id", None) == run.user_id
        ]
        return run.model_copy(
            update={
                "run_count": len(siblings),
                "verdict_is_contested": self._contested(siblings),
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
        """Newest usable run, preferring a finished one.

        A completed run beats an in-flight one: a caller asking this question
        wants an answer now, and the run still executing will surface on its
        own once done.

        ``bypass_owner_check`` is the admin escape hatch -- structurally
        distinct from ``owner`` so ``owner=None`` alone can never be
        mistaken for "no filter" (it still means "unclaimed rows only").
        """
        siblings = self._siblings(ticker, analysis_date, profile)
        if not bypass_owner_check:
            siblings = [r for r in siblings if getattr(r, "user_id", None) == owner]
        if not siblings:
            return None

        completed = [r for r in siblings if r.status is RunStatus.COMPLETED]
        chosen = completed[0] if completed else siblings[0]
        return chosen.model_copy(
            update={
                "cached": True,
                "run_count": len(siblings),
                "verdict_is_contested": self._contested(siblings),
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
        siblings = self._siblings(ticker, analysis_date, profile)
        if not bypass_owner_check:
            siblings = [r for r in siblings if getattr(r, "user_id", None) == owner]
        if not siblings:
            return None
        return RunHistory(
            ticker=ticker,
            analysis_date=analysis_date,
            profile=profile,
            run_count=len(siblings),
            ratings=[
                _rating_of(r) for r in siblings if r.status is RunStatus.COMPLETED
            ],
            verdict_is_contested=self._contested(siblings),
            runs=[RunSummary.model_validate(r, from_attributes=True) for r in siblings],
        )

    async def count_runs_today(self, requested_by: str | None = None) -> int:
        # The in-memory store does not record requesters, so this counts
        # everything. Adequate for tests; the SQL store is the real one.
        return len(self._runs)

    async def list(
        self, ticker: str | None, limit: int, offset: int, owner: str | None
    ) -> list[RunSummary]:
        runs = [
            r
            for r in self._runs.values()
            if owner is None or getattr(r, "user_id", None) == owner
        ]
        if ticker is not None:
            runs = [r for r in runs if r.ticker == ticker]
        # Newest first, with id as a tiebreak so pagination is deterministic
        # when several runs share a timestamp.
        runs.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        return [
            RunSummary.model_validate(r, from_attributes=True)
            for r in runs[offset : offset + limit]
        ]

    async def request_stop(self, run_id: str) -> RunDetail | None:
        # No real worker cooperatively polling a flag for this dev-only
        # store (no run_events table either -- see get_events_since below),
        # so both queued and running are cancelled directly rather than
        # modeling the cooperative-check delay the real SqlRunStore has.
        run = self._runs.get(run_id)
        if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
            return None
        updated = run.model_copy(update={"status": RunStatus.CANCELLED})
        self._runs[run_id] = updated
        return updated

    async def get_events_since(self, run_id: str, after_seq: int) -> list[RunEventOut]:
        # This store never captures streamed token events (it has no
        # run_events table, nor any equivalent), so there is truthfully
        # nothing to return regardless of run_id or after_seq. An empty list
        # is the honest answer, not a stub — do not fabricate events here.
        return []

    async def add_push_subscription(
        self, run_id: str, endpoint: str, p256dh: str, auth: str
    ) -> None:
        self._push_subscriptions.setdefault(run_id, []).append(
            PushSubscription(
                run_id=run_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                created_at=datetime.now(timezone.utc),
            )
        )

    async def get_push_subscriptions(self, run_id: str) -> list[PushSubscription]:
        return list(self._push_subscriptions.get(run_id, []))

    async def clear_push_subscriptions(self, run_id: str) -> None:
        self._push_subscriptions.pop(run_id, None)


_store: RunStore | None = None


def get_run_store() -> RunStore:
    """The database-backed store by default.

    Built lazily so importing this module never touches the filesystem —
    tests override the dependency before any request is served, and /health
    must work even if the database is unreachable.
    """
    global _store
    if _store is None:
        from api.store import SqlRunStore

        _store = SqlRunStore()
    return _store


RunStoreDep = Annotated[RunStore, Depends(get_run_store)]
