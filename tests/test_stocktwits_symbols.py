"""StockTwits symbol-mapping regression tests.

Every Indian ticker in this codebase carries a yfinance-style `.NS`/`.BO`
suffix, but StockTwits indexes Indian equities under `.NSE`. Passing the
yfinance symbol through unchanged 404'd for every single Indian ticker,
which surfaced in reports as "<stocktwits unavailable: HTTPError>" and was
misread as StockTwits being down (LAURUSLABS.BO run, 2026-08-10).
"""

import pytest

from tradingagents.dataflows.stocktwits import (
    _fetch_stocktwits_messages_cached,
    _symbol_candidates,
)


@pytest.mark.unit
def test_nse_ticker_maps_to_stocktwits_nse_suffix():
    assert _symbol_candidates("RELIANCE.NS")[0] == "RELIANCE.NSE"


@pytest.mark.unit
def test_bse_ticker_also_maps_to_nse_namespace():
    # StockTwits has no `.BSE` namespace at all — LAURUSLABS.BSE 404s while
    # LAURUSLABS.NSE returns a full stream, so BSE-suffixed symbols must map
    # onto `.NSE` rather than to a `.BSE` form that does not exist.
    assert _symbol_candidates("LAURUSLABS.BO")[0] == "LAURUSLABS.NSE"


@pytest.mark.unit
def test_india_ticker_falls_back_to_bare_symbol():
    assert _symbol_candidates("LAURUSLABS.BO") == ("LAURUSLABS.NSE", "LAURUSLABS")


@pytest.mark.unit
def test_non_india_ticker_is_passed_through_unchanged():
    assert _symbol_candidates("NVDA") == ("NVDA",)


@pytest.mark.unit
def test_first_resolving_candidate_is_used(monkeypatch):
    """A 404 on `.NSE` must fall through to the bare symbol, not abort."""
    tried = []

    def fake_request(symbol, timeout):
        tried.append(symbol)
        if symbol.endswith(".NSE"):
            return None  # simulate 404
        return {"messages": [{"body": "hello", "user": {"username": "u"}}]}

    monkeypatch.setattr(
        "tradingagents.dataflows.stocktwits._request_stream", fake_request
    )
    _fetch_stocktwits_messages_cached.cache_clear()
    result = _fetch_stocktwits_messages_cached("LAURUSLABS.BO", 5, 10.0)

    assert tried == ["LAURUSLABS.NSE", "LAURUSLABS"]
    assert "hello" in result
    _fetch_stocktwits_messages_cached.cache_clear()


@pytest.mark.unit
def test_all_candidates_failing_reports_what_was_tried(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.stocktwits._request_stream",
        lambda symbol, timeout: None,
    )
    _fetch_stocktwits_messages_cached.cache_clear()
    result = _fetch_stocktwits_messages_cached("LAURUSLABS.BO", 5, 10.0)

    # The old message ("<stocktwits unavailable: HTTPError>") gave no way to
    # tell a wrong-symbol bug from an outage; the symbols tried must be shown.
    assert "LAURUSLABS.NSE" in result
    assert "unavailable" in result
    _fetch_stocktwits_messages_cached.cache_clear()
