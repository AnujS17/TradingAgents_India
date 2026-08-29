"""The worker: claims queued runs and executes them.

Run it as a SEPARATE process from the API:

    python -m api.worker

The API must answer in milliseconds; an analysis takes 220-800 seconds. Those
cannot share a process, which is the whole reason this file exists.

Polling the database rather than subscribing to Redis keeps the prototype at
zero external services. The cost is up to ``poll_interval`` of latency before a
job starts, which is irrelevant next to a four-minute run.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import traceback

from api.db import Run, create_tables
from api.schemas import AnalysisProfile
from api.settings import get_settings
from api.store import SqlRunStore

logger = logging.getLogger("api.worker")

POLL_INTERVAL_SECONDS = 3.0


def _sync_db_path() -> str:
    """RunEventWriter needs a plain filesystem path; _database_url()
    returns a SQLAlchemy async URL. Only supports the sqlite+aiosqlite
    scheme this project actually uses (api/db.py's own docstring: SQLite
    by default, Postgres is a future migration) -- raise clearly rather
    than silently misbehaving if that ever changes."""
    from api.db import _database_url

    url = _database_url()
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise RuntimeError(
            f"RunEventWriter requires a sqlite+aiosqlite database URL, got: {url}"
        )
    return url[len(prefix):]


async def _notify_completion(store: SqlRunStore, row: Run, title: str, body: str) -> None:
    """Best-effort push notification for one run's terminal state.

    Never raises, and never leaves the run waiting on it: this always runs
    AFTER the row's status is already durably written, so a notification
    failure (or the whole push subsystem being unreachable) can never turn
    a real success or failure into something worse. Each send is pushed to
    a thread -- pywebpush.webpush does a blocking HTTP POST per
    subscriber, and awaiting that inline would stall every other lane in
    this same worker process for however long the push service takes to
    respond.

    The try/except below is not redundant with push.send's own -- send()
    guarantees IT never raises, but this function also does its own I/O
    (get_push_subscriptions, clear_push_subscriptions) that send() has no
    control over. Nothing in worker_lane's loop wraps this call, and
    worker_loop runs every lane under asyncio.gather, whose default
    behavior on an unhandled exception in one task is to cancel every
    sibling task and re-raise -- so an unguarded failure here would not
    just skip one notification, it would take down the whole worker
    process. Caught during development by a test that made push.send raise
    directly (simulating something failing outside push.send's own
    guarantee) rather than return False.
    """
    try:
        subscriptions = await store.get_push_subscriptions(row.id)
        if not subscriptions:
            return

        import api.push as push
        from api.settings import get_settings

        vapid_subject = get_settings().vapid_subject
        payload = {"title": title, "body": body, "url": f"/runs/{row.id}"}
        for sub in subscriptions:
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            await asyncio.to_thread(push.send, subscription_info, payload, vapid_subject)

        # Used (or attempted) either way -- see PushSubscription's docstring
        # on why a used row is never kept around.
        await store.clear_push_subscriptions(row.id)
    except Exception as exc:  # noqa: BLE001 - a courtesy on top of an already-decided run
        logger.warning("push notification for run %s failed: %s", row.id, exc)


async def execute_run(store: SqlRunStore, row: Run) -> None:
    """Run one analysis and record the outcome.

    Every failure is caught and written to the row. An uncaught exception here
    would kill the worker and leave the run stuck in ``running`` forever, with
    the user polling an answer that never arrives.
    """
    from api.service import RunCancelled, run_analysis
    from api.streaming import RunEventWriter

    logger.info("running %s %s (%s)", row.ticker, row.analysis_date, row.profile)

    writer = RunEventWriter(_sync_db_path(), row.id)
    try:
        # The engine call is synchronous and CPU/IO-bound for minutes. Pushing
        # it to a thread keeps this loop responsive — otherwise the event loop
        # is blocked and nothing else in the process can run, including a
        # clean shutdown.
        verdict, reports = await asyncio.to_thread(
            run_analysis,
            row.ticker,
            row.analysis_date,
            AnalysisProfile(row.profile),
            row.refresh_data,
            writer.on_token,
            writer.should_stop,
            row.requested_time_horizon,
            resume=bool(row.resume),
        )
    except RunCancelled:
        logger.info("run %s stopped by request", row.id)
        writer.flush_all()
        writer.close()
        await store.mark_cancelled(row.id)
        await _notify_completion(
            store, row, f"{row.ticker} analysis stopped",
            "You stopped this analysis before it finished.",
        )
        return
    except Exception as exc:  # noqa: BLE001 - record and continue
        logger.exception("run %s failed", row.id)
        writer.flush_all()
        writer.close()
        await store.mark_failed(row.id, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        await _notify_completion(
            store, row, f"{row.ticker} analysis failed",
            "Tap to see what happened -- you may be able to resume it.",
        )
        return

    writer.flush_all()
    writer.close()
    await store.mark_completed(row.id, verdict, reports)
    logger.info("completed %s (%s)", row.id, verdict.rating or "no rating")
    await _notify_completion(
        store, row, f"{row.ticker} analysis complete",
        f"Rating: {verdict.rating}" if verdict.rating else "Tap to see the full report.",
    )


async def worker_lane(lane_id: int, stop: asyncio.Event, store: SqlRunStore) -> None:
    """One cashier. Runs until told to stop, always claiming and finishing
    one row before claiming the next -- concurrency comes from running
    several lanes side by side (see worker_loop), not from anything in here.

    Safe to run N of these against the same store: claim_next_run's UPDATE is
    conditional on the row still being queued, so two lanes racing for the
    same row never both win."""
    while not stop.is_set():
        row = await store.claim_next_run()
        if row is None:
            # Nothing queued. Sleep, but wake immediately on shutdown rather
            # than making Ctrl-C wait out the interval.
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
            continue
        logger.debug("lane %d claimed %s", lane_id, row.id)
        await execute_run(store, row)


async def worker_loop(
    stop: asyncio.Event,
    store: SqlRunStore | None = None,
    concurrency: int | None = None,
) -> None:
    store = store or SqlRunStore()
    if concurrency is None:
        concurrency = get_settings().worker_concurrency
    await asyncio.gather(
        *(worker_lane(lane_id, stop, store) for lane_id in range(concurrency))
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    await create_tables()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows has no add_signal_handler for these; KeyboardInterrupt
            # below is the fallback path there.
            pass

    concurrency = get_settings().worker_concurrency
    logger.info(
        "worker started; %d lane(s), polling every %.0fs", concurrency, POLL_INTERVAL_SECONDS
    )
    try:
        await worker_loop(stop, concurrency=concurrency)
    finally:
        logger.info("worker stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
