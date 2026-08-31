"""run_prefetches_concurrently and its use in news_analyst/sentiment_analyst.

news_analyst.py fired 4-5 independent network calls one at a time, and
sentiment_analyst.py fired 4 more the same way -- nine serial round-trips to
different vendors, none reading another's output, for no reason beyond
having been written that way. Measured live (2026-08-31): roughly 76% of a
run's span after the first token had no model output at all, and this
pre-fetch phase runs BEFORE any LLM call, so it sits entirely outside that
figure as pure added latency. fundamentals_analyst.py already parallelized
its own 8-fetch plan for the identical reason (see its _run_prefetches);
this generalises that pattern into agent_utils.run_prefetches_concurrently
and applies it to the other two analysts.
"""

import time
from unittest.mock import patch

import pytest

from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.agents.utils.agent_utils import run_prefetches_concurrently


def _state():
    return {
        "messages": [("human", "ORCL")],
        "sentiment_messages": [("human", "ORCL")],
        "news_messages": [("human", "ORCL")],
        "company_of_interest": "ORCL",
        "trade_date": "2026-06-03",
        "asset_type": "stock",
        "instrument_context": "The instrument to analyze is `ORCL`.",
    }


class PlainLLM:
    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        return AIMessage(content="grounded report")


# ---------------------------------------------------------------------------
# run_prefetches_concurrently itself
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_results_come_back_in_plan_order_regardless_of_completion_order():
    """Callers unpack results positionally (news_analyst.py: results[:4];
    sentiment_analyst.py: a 4-way tuple unpack) -- order must be the plan's
    order, not whichever thunk happened to finish first."""

    def slow(value, delay):
        time.sleep(delay)
        return value

    plan = [
        ("first", {}, lambda: slow("a", 0.15)),
        ("second", {}, lambda: slow("b", 0.05)),   # finishes before "first"
        ("third", {}, lambda: slow("c", 0.10)),
    ]

    assert run_prefetches_concurrently(plan) == ["a", "b", "c"]


@pytest.mark.unit
def test_a_failing_thunk_degrades_to_a_marker_others_are_unaffected():
    """Matches every deterministic fetcher's own documented contract in this
    codebase -- a missing source must not abort the whole analysis, and the
    model needs to SEE the gap rather than silently reasoning on incomplete
    data. Defence in depth: the real fetchers already degrade internally
    (news_analyst.py's own comment), this is the backstop if one ever
    doesn't."""

    def boom():
        raise RuntimeError("vendor exploded")

    plan = [
        ("ok_source", {}, lambda: "real data"),
        ("bad_source", {}, boom),
    ]

    results = run_prefetches_concurrently(plan)

    assert results[0] == "real data"
    assert "bad_source unavailable" in results[1]
    assert "vendor exploded" in results[1]


@pytest.mark.unit
def test_independent_fetches_run_concurrently_not_serially():
    """The actual point of this change, measured directly: N sources each
    taking `delay` must complete in close to ONE delay, not N delays. Loose
    bound (not delay*N) to avoid flaking on a loaded machine while still
    failing outright if this regresses to sequential -- same style as
    test_parallel_analysts.py::test_parallel_is_faster_than_sequential."""
    delay = 0.2
    n = 5
    plan = [(f"source_{i}", {}, lambda: time.sleep(delay)) for i in range(n)]

    t0 = time.perf_counter()
    run_prefetches_concurrently(plan)
    elapsed = time.perf_counter() - t0

    assert elapsed < delay * n * 0.6, (
        f"elapsed={elapsed:.2f}s not meaningfully faster than "
        f"sequential={delay * n:.2f}s -- prefetches are not running concurrently"
    )


# ---------------------------------------------------------------------------
# The two analysts that were switched to it
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_news_analyst_prefetches_concurrently(monkeypatch):
    delay = 0.15

    def slow(value):
        time.sleep(delay)
        return value

    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_news.func",
        lambda ticker, start_date, end_date: slow("company news"),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_global_news.func",
        lambda curr_date: slow("global news"),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_global_india_news",
        lambda: slow("india global news"),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_corporate_announcements",
        lambda ticker, curr_date: slow("filings"),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=20: slow("social wire"),
    )

    t0 = time.perf_counter()
    result = create_news_analyst(PlainLLM())(_state())
    elapsed = time.perf_counter() - t0

    assert "company news" in result["news_report"]
    assert elapsed < delay * 5 * 0.6, (
        f"news_analyst prefetch took {elapsed:.2f}s, not meaningfully faster "
        f"than sequential {delay * 5:.2f}s"
    )


@pytest.mark.unit
def test_news_analyst_skips_the_stocktwits_fetch_when_disabled(monkeypatch):
    """Regression guard on the conditional branch: disabling StockTwits must
    still mean the fetcher is never CALLED (not just discarded after),
    exactly as it did before this refactor."""
    called = {"stocktwits": False}

    def mark_called(*a, **k):
        called["stocktwits"] = True
        return "should not appear"

    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_news.func",
        lambda ticker, start_date, end_date: "company news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_global_news.func",
        lambda curr_date: "global news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_global_india_news",
        lambda: "india global news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_corporate_announcements",
        lambda ticker, curr_date: "filings",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_stocktwits_messages", mark_called
    )
    from tradingagents.dataflows.config import get_config, set_config

    set_config({**get_config(), "news_include_stocktwits": False})
    try:
        result = create_news_analyst(PlainLLM())(_state())
    finally:
        set_config({**get_config(), "news_include_stocktwits": True})

    assert called["stocktwits"] is False
    assert [c["name"] for c in result["audit_tool_calls"]] == [
        "get_news",
        "get_global_news",
        "fetch_global_india_news",
        "fetch_corporate_announcements",
    ]


@pytest.mark.unit
def test_sentiment_analyst_prefetches_concurrently(monkeypatch):
    delay = 0.15

    def slow(value):
        time.sleep(delay)
        return value

    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.get_news.func",
        lambda ticker, start_date, end_date: slow("news block"),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=30: slow("stocktwits block"),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts",
        lambda ticker, subreddits=None: slow("reddit block"),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_ticker_india_news",
        lambda ticker: slow("india news block"),
    )

    t0 = time.perf_counter()
    result = create_sentiment_analyst(PlainLLM())(_state())
    elapsed = time.perf_counter() - t0

    assert "stocktwits block" in result["sentiment_report"]
    assert elapsed < delay * 4 * 0.6, (
        f"sentiment_analyst prefetch took {elapsed:.2f}s, not meaningfully "
        f"faster than sequential {delay * 4:.2f}s"
    )
