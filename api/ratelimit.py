"""Spend controls.

Every queued run costs real LLM money, and this is a public on-demand service
with a "run it again" button. Without a cap, one client in a loop can spend a
month's budget overnight. These limits exist from the first working version
rather than being added after the first surprise invoice.

Deliberately counted from the database rather than an in-memory counter: an
API restart must not reset someone's daily allowance, and two API processes
must share one budget.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from api.settings import get_settings


class BudgetExceeded(HTTPException):
    def __init__(self, detail: str, retry_after_seconds: int = 3600) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after_seconds)},
        )


def client_identity(request: Request) -> str:
    """Best-effort caller identity for per-client limits.

    IP only, for now — there are no accounts yet. Honours X-Forwarded-For
    because behind a proxy every request otherwise appears to come from the
    proxy itself, collapsing all users into one bucket and locking everyone
    out once any one of them hits the cap.

    This is spoofable. It is a cost guardrail, not a security control, and it
    should be replaced by an account id once there are accounts.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_budget(store, requested_by: str) -> None:
    """Refuse a NEW run when a cap is hit. Cached reads are never blocked.

    Ordering matters: the kill switch is checked first, then the global cap,
    then the per-client one, so an operator-triggered stop cannot be masked by
    a client-specific message.
    """
    settings = get_settings()

    if settings.kill_switch_enabled:
        raise BudgetExceeded(
            "New analyses are temporarily disabled. Existing results are still "
            "available.",
            retry_after_seconds=3600,
        )

    global_today = await store.count_runs_today()
    if global_today >= settings.max_runs_global_per_day:
        raise BudgetExceeded(
            "The service has reached its daily analysis limit. Existing "
            "results are still available; new analyses resume tomorrow.",
            retry_after_seconds=3600,
        )

    mine_today = await store.count_runs_today(requested_by=requested_by)
    if mine_today >= settings.max_runs_per_ip_per_day:
        raise BudgetExceeded(
            f"You have requested {mine_today} analyses today, which is the "
            f"limit of {settings.max_runs_per_ip_per_day}. Previously "
            "completed analyses are still available to read.",
            retry_after_seconds=3600,
        )
