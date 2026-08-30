"""Snapshot-cache coverage for the fundamentals and remaining news vendors.

Extends dataflows/snapshot_cache.py (see test_snapshot_cache.py) to the
fetchers that were still missing it: y_finance's 4 fundamentals functions
(the DEFAULT fundamental_data vendor -- default_config.py's data_vendors),
alpha_vantage_fundamentals.py (the fallback vendor), and yfinance_news.py
(both functions are in merged_news_vendors, so they run on every single
analysis, not just as a fallback).

Before this, none of these had any persistence beyond the single Python
process that fetched them -- a same-day re-run for a different time_horizon
re-fetched every one of them from the live vendor, even though nothing about
time_horizon ever reaches a dataflow function's arguments.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.dataflows import alpha_vantage_fundamentals, y_finance, yfinance_news
from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows.snapshot_cache import clear_snapshot_date, set_snapshot_date
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture
def cache_dir(tmp_path):
    before = dict(get_config())
    set_config({**DEFAULT_CONFIG, "data_cache_dir": str(tmp_path)})
    y_finance._fetch_info_cached.cache_clear()
    y_finance._fetch_balance_sheet_csv.cache_clear()
    y_finance._fetch_cashflow_csv.cache_clear()
    y_finance._fetch_income_statement_csv.cache_clear()
    yfinance_news._fetch_news_cached.cache_clear()
    yfinance_news._search_global_news_cached.cache_clear()
    yield tmp_path
    set_config(before)
    clear_snapshot_date()
    y_finance._fetch_info_cached.cache_clear()
    y_finance._fetch_balance_sheet_csv.cache_clear()
    y_finance._fetch_cashflow_csv.cache_clear()
    y_finance._fetch_income_statement_csv.cache_clear()
    yfinance_news._fetch_news_cached.cache_clear()
    yfinance_news._search_global_news_cached.cache_clear()


@pytest.mark.unit
def test_yfinance_balance_sheet_replays_across_process_boundaries(cache_dir):
    """The point of this whole change: a same-day re-run (e.g. triggered by
    a different time_horizon) must not call yfinance again.

    get_balance_sheet makes two yf.Ticker() calls per invocation -- one for
    the statement (_fetch_balance_sheet_csv) and one for the currency-
    mismatch check (_statement_currency_warning -> _fetch_info_cached) --
    both routed through the same mock here, so `calls` counts both. The
    assertion is on GROWTH across the second call, not a fixed total.
    """
    calls = []

    def make_ticker(_symbol):
        calls.append(1)
        ticker = MagicMock()
        ticker.balance_sheet = pd.DataFrame({pd.Timestamp("2025-12-31"): [100]}, index=["Cash"])
        ticker.info = {}
        return ticker

    set_snapshot_date("2026-08-28")
    with patch("tradingagents.dataflows.y_finance.yf.Ticker", side_effect=make_ticker):
        first = y_finance.get_balance_sheet("HAL.NS", freq="annual", curr_date="2026-08-28")
        calls_after_first = len(calls)
        # A cleared in-process memo stands in for a brand new run's process
        # -- only the directory on disk is shared, same as
        # test_snapshot_cache.py's test_survives_a_new_process. Both caches
        # cleared since both are exercised by this one call.
        y_finance._fetch_balance_sheet_csv.cache_clear()
        y_finance._fetch_info_cached.cache_clear()
        second = y_finance.get_balance_sheet("HAL.NS", freq="annual", curr_date="2026-08-28")

    assert first == second
    assert "Cash,100" in first
    assert len(calls) == calls_after_first, (
        "second call must be served entirely from the snapshot cache, not yfinance"
    )


@pytest.mark.unit
def test_yfinance_info_is_shared_across_the_four_fundamentals_functions(cache_dir):
    """get_fundamentals and each statement function's currency-mismatch
    check used to each fetch .info independently -- 4 live calls per run for
    data that cannot differ between them. They must now share one fetch.

    A plain class (not MagicMock) here deliberately: assigning a `property`
    onto `type(a_mock_instance)` patches the shared MagicMock class itself
    for every mock in the process, not just this one instance.
    """

    class FakeTicker:
        balance_sheet = pd.DataFrame({pd.Timestamp("2025-12-31"): [1]}, index=["Cash"])

        @property
        def info(self):
            calls.append(1)
            return {"financialCurrency": "INR", "currency": "INR", "longName": "HAL"}

    calls = []
    set_snapshot_date("2026-08-28")
    with patch("tradingagents.dataflows.y_finance.yf.Ticker", side_effect=lambda _symbol: FakeTicker()):
        y_finance.get_fundamentals("HAL.NS", "2026-08-28")
        y_finance.get_balance_sheet("HAL.NS", freq="annual", curr_date="2026-08-28")

    assert len(calls) == 1, ".info must be fetched once and reused, not once per fundamentals function"


@pytest.mark.unit
def test_alpha_vantage_statement_freq_annual_and_quarterly_hit_the_api_once(cache_dir):
    """Pre-existing bug, exposed (and fixed) by adding this cache: Alpha
    Vantage's BALANCE_SHEET/CASH_FLOW/INCOME_STATEMENT endpoints return both
    annualReports and quarterlyReports in ONE response -- freq is accepted
    by these functions but never reached the request. The fundamentals
    analyst always calls both freqs, so this was two identical live calls
    per statement, every run. Routing both through the same cache key
    collapses them into one.

    _make_api_request always returns the raw response TEXT (a str), never a
    parsed dict -- see its docstring/return type -- so the fake here mirrors
    that shape rather than a parsed object.
    """
    calls = []

    def fake_request(function_name, params):
        calls.append(function_name)
        return '{"annualReports": [{"fiscalDateEnding": "2025-03-31"}], "quarterlyReports": [{"fiscalDateEnding": "2026-06-30"}]}'

    with patch("tradingagents.dataflows.alpha_vantage_common._make_api_request", side_effect=fake_request), \
         patch("tradingagents.dataflows.alpha_vantage_common.get_api_key", return_value="k"):
        annual = alpha_vantage_fundamentals.get_balance_sheet("HAL.NS", freq="annual", curr_date="2026-08-28")
        quarterly = alpha_vantage_fundamentals.get_balance_sheet("HAL.NS", freq="quarterly", curr_date="2026-08-28")

    assert calls == ["BALANCE_SHEET"], "both freqs must resolve to a single live BALANCE_SHEET call"
    assert annual == quarterly, "both freqs replay the identical cached response"
    assert "annualReports" in annual and "quarterlyReports" in annual


@pytest.mark.unit
def test_filter_reports_by_date_does_not_mutate_a_dict_input():
    """_filter_reports_by_date's isinstance(result, dict) branch is dead in
    the real alpha_vantage_fundamentals flow today (_make_api_request always
    returns a raw string, never a parsed dict -- a separate, pre-existing
    gap, not this change's to fix). But _cached_api_request's lru_cache
    would hand back the SAME object on every hit for ANY return type, so if
    that string-vs-dict gap is ever closed, an in-place filter would corrupt
    the shared cache entry the way this test guards against directly."""
    from tradingagents.dataflows.alpha_vantage_fundamentals import _filter_reports_by_date

    raw = {
        "annualReports": [{"fiscalDateEnding": "2020-03-31"}, {"fiscalDateEnding": "2026-03-31"}],
        "quarterlyReports": [],
    }

    filtered = _filter_reports_by_date(raw, "2020-06-01")
    assert len(filtered["annualReports"]) == 1

    # The original object handed to us (standing in for a cached, shared
    # object) must be untouched -- a second, wider-window call against the
    # SAME source must still see both entries.
    assert len(raw["annualReports"]) == 2
    filtered_again = _filter_reports_by_date(raw, "2026-12-31")
    assert len(filtered_again["annualReports"]) == 2


@pytest.mark.unit
def test_yfinance_news_replays_across_process_boundaries(cache_dir):
    """get_news_yfinance also calls yf.Ticker() a second, unrelated time via
    _company_specificity_note -> company_names.resolve_company_name -- a
    pre-existing lookup, nothing to do with this change -- so the assertion
    is on ticker.get_news's own call count specifically, not on how many
    times yf.Ticker() was constructed."""
    ticker = MagicMock()
    ticker.get_news.return_value = [
        {"title": "HAL wins order", "summary": "", "publisher": "Reuters", "link": "https://x"}
    ]
    ticker.info = {}

    set_snapshot_date("2026-08-28")
    with patch("tradingagents.dataflows.yfinance_news.yf.Ticker", return_value=ticker):
        first = yfinance_news.get_news_yfinance("HAL.NS", "2026-08-01", "2026-08-28")
        yfinance_news._fetch_news_cached.cache_clear()
        second = yfinance_news.get_news_yfinance("HAL.NS", "2026-08-01", "2026-08-28")

    assert first == second
    assert "HAL wins order" in first
    assert ticker.get_news.call_count == 1, "second call must be served from the snapshot cache, not yfinance"
