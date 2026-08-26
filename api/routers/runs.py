"""Analysis run endpoints.

Shape is driven by one fact: **a run takes 220-800 seconds**, so it can never
be an HTTP request. Every endpoint here is either "start a job" or "ask about
a job"; nothing blocks on the engine.

Persistence and the queue land in the next step. The handlers below are wired
against a repository interface so that swapping the in-memory stub for
Postgres + RQ does not change this file.
"""

import asyncio
from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from api.dependencies import RunStoreDep
from api.ratelimit import client_identity, enforce_budget
from api.schemas import (
    AnalysisProfile,
    AnalysisRequest,
    RunAccepted,
    RunDetail,
    RunHistory,
    RunStatus,
    RunSummary,
)

router = APIRouter()

# Rough client-facing guidance only. Measured on SIEMENS.NS 2026-08-12:
# fast 222s, detailed 801s. Not a promise, and not used for timeouts.
_ESTIMATED_SECONDS = {
    AnalysisProfile.FAST: 240,
    AnalysisProfile.DETAILED: 840,
}


@router.post(
    "/analyze",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["runs"],
)
async def request_analysis(
    payload: AnalysisRequest,
    store: RunStoreDep,
    request: Request,
    response: Response,
) -> RunAccepted:
    """Queue an analysis, or hand back the existing one.

    Returns **200** with the existing run when this ticker/date/profile has
    already been analysed, and **202** when a new job was queued. Callers can
    treat both as success; the status code tells them whether they paid for a
    run. Serving repeats from cache is what makes on-demand analysis
    affordable for a public audience, and it also means two users asking the
    same question get the same answer rather than two independently sampled
    verdicts.
    """
    analysis_date = payload.analysis_date or Date.today()

    # force=true skips the cache lookup entirely and always spends a run. The
    # existing one is NOT replaced — runs accumulate, so a user can compare a
    # fresh answer against the earlier one. That comparison is the point: the
    # day's inputs are snapshotted, so two runs read identical data and any
    # difference is the model telling you the call is borderline.
    if not payload.force:
        existing = await store.find(payload.ticker, analysis_date, payload.profile)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return RunAccepted(
                id=existing.id,
                status=existing.status,
                poll_url=f"/runs/{existing.id}",
                estimated_seconds=0,
            )

    # Only NEW runs are charged against the budget. A cached read costs
    # nothing, so it is never blocked — a user who has hit their limit can
    # still read every analysis that already exists.
    requested_by = client_identity(request)
    await enforce_budget(store, requested_by)

    run = await store.create(
        payload.ticker,
        analysis_date,
        payload.profile,
        refresh_data=payload.refresh_data,
        requested_by=requested_by,
        time_horizon=payload.time_horizon,
    )
    return RunAccepted(
        id=run.id,
        status=run.status,
        poll_url=f"/runs/{run.id}",
        estimated_seconds=_ESTIMATED_SECONDS[payload.profile],
    )


@router.post("/runs/{run_id}/stop", response_model=RunDetail, tags=["runs"])
async def stop_run(run_id: str, store: RunStoreDep) -> RunDetail:
    """Ask a queued or running analysis to stop.

    Cooperative, not instant, for a running analysis: the worker checks a
    flag once per streamed chunk (see RunEventWriter.should_stop() and
    propagate_streaming's loop), typically within about one token's
    latency but never mid-way through an LLM call already in flight. A
    still-queued run (no worker has claimed it yet) is cancelled outright.

    404 covers both "no such run" and "this run already finished" — the
    caller cannot stop what is not running either way, and doesn't need to
    distinguish the two to know that.
    """
    updated = await store.request_stop(run_id)
    if updated is None:
        raise HTTPException(
            status_code=404, detail="Run not found, or it has already finished"
        )
    return updated


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["runs"],
)
async def resume_run(
    run_id: str, store: RunStoreDep, request: Request
) -> RunAccepted:
    """Continue a failed run instead of starting over from scratch.

    Queues a NEW run (same ticker/date/profile/time_horizon as the failed
    one) rather than mutating it in place, so the failed row stays in the
    run history as an honest record of what happened. The new run is marked
    internally so the engine may pick up whatever checkpoint the failed
    attempt left behind (see TradingAgentsGraph.propagate_streaming's
    ``resume`` parameter) -- if nothing was actually checkpointed (the run
    failed before any stage finished, for example), it degrades gracefully
    to a normal fresh run instead of erroring.

    404 covers both "no such run" and "that run isn't in a failed state" --
    a caller cannot resume what didn't fail either way, and doesn't need to
    distinguish the two to know that. Budget-checked the same as a normal
    /analyze call: continuing a run still spends real LLM calls for
    whatever's left.
    """
    requested_by = client_identity(request)
    await enforce_budget(store, requested_by)

    new_run = await store.create_resume(run_id, requested_by=requested_by)
    if new_run is None:
        raise HTTPException(
            status_code=404,
            detail="Run not found, or it did not fail (only a failed run can be resumed)",
        )
    return RunAccepted(
        id=new_run.id,
        status=new_run.status,
        poll_url=f"/runs/{new_run.id}",
        estimated_seconds=_ESTIMATED_SECONDS[new_run.profile],
    )


@router.get(
    "/runs/{ticker}/{analysis_date}/history",
    response_model=RunHistory,
    tags=["runs"],
)
async def get_run_history(
    ticker: str,
    analysis_date: Date,
    store: RunStoreDep,
    profile: AnalysisProfile = AnalysisProfile.FAST,
) -> RunHistory:
    """Every analysis of one question, so repeat runs can be compared.

    This is what backs a "you have run this 3 times, and they disagreed" view.
    Hiding that would be the dishonest option — the runs read identical data,
    so a split is real information about how balanced the evidence is.
    """
    history = await store.history(ticker.strip().upper(), analysis_date, profile)
    if history is None:
        raise HTTPException(status_code=404, detail="No analyses for that ticker and date")
    return history


@router.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"])
async def get_run(run_id: str, store: RunStoreDep) -> RunDetail:
    """Poll a run. Carries reports only once status is ``completed``."""
    run = await store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/stream", tags=["runs"])
async def stream_run(run_id: str, store: RunStoreDep, request: Request) -> StreamingResponse:
    """Server-Sent Events: token-level live view of an in-progress run.

    Honors Last-Event-ID (sent automatically by a reconnecting browser
    EventSource) so a refresh mid-run resumes rather than replaying from
    the start. Polls run_events via the same WAL-mode SQLite pattern
    api/db.py already documents for concurrent reader/writer access.

    Registered ABOVE /runs/{ticker}/{analysis_date} on purpose: both are
    two-segment paths under /runs, and FastAPI matches route order, so this
    one must come first or every "stream" would be swallowed as a bogus
    analysis_date and 422 instead of streaming.
    """
    last_seq = int(request.headers.get("Last-Event-ID", "0") or "0")

    async def event_source():
        seq = last_seq
        while True:
            if await request.is_disconnected():
                return
            run = await store.get(run_id)
            if run is None:
                return
            events = await store.get_events_since(run_id, seq)
            for event in events:
                seq = event.seq
                yield f"id: {event.seq}\ndata: {event.model_dump_json()}\n\n"
            if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get(
    "/runs/{ticker}/{analysis_date}", response_model=RunDetail, tags=["runs"]
)
async def get_run_by_ticker(
    ticker: str,
    analysis_date: Date,
    store: RunStoreDep,
    profile: AnalysisProfile = AnalysisProfile.FAST,
) -> RunDetail:
    """Fetch a completed analysis by what it is *about* rather than by job id.

    This is the endpoint a UI actually uses on a stock page: it does not know
    a run id, only which company and day the user is looking at.
    """
    run = await store.find(ticker.strip().upper(), analysis_date, profile)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="No analysis for that ticker and date. POST /analyze to request one.",
        )
    return run


@router.get("/runs", response_model=list[RunSummary], tags=["runs"])
async def list_runs(
    store: RunStoreDep,
    ticker: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunSummary]:
    return await store.list(
        ticker=ticker.strip().upper() if ticker else None,
        limit=limit,
        offset=offset,
    )
