"""load_ohlcv's Alpha Vantage fallback when yfinance returns no data.

APOLLOHOSP.NS, 2026-08-25: yfinance returned a 401 "User is unable to
access this feature" followed by "possibly delisted", the deterministic
Verified Market Snapshot failed outright, and the Market Analyst had to
reconstruct a technical read through its own get_stock_data tool call
instead -- costing an 8-minute gap in the run. load_ohlcv had zero
fallback (unlike get_stock_data, which routes through interface.py's
alpha_vantage vendor); this gives it the same resilience directly.

Also guards a real bug found while building this: alpha_vantage_stock.py's
get_stock() called TIME_SERIES_DAILY_ADJUSTED, which is gated behind Alpha
Vantage's premium tier -- confirmed live, a free key gets an "Information:
this is a premium endpoint" body instead of any data. That made every
caller of get_stock() (including get_stock_data's own alpha_vantage
vendor) silently non-functional before this fix.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.stockstats_utils import (
    _load_ohlcv_from_alpha_vantage,
    _to_alpha_vantage_symbol,
    load_ohlcv,
)
from tradingagents.dataflows.config import set_config
import tradingagents.default_config as default_config


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path):
    """load_ohlcv caches to disk -- point it at a throwaway directory so
    these tests never read or write the real cache."""
    set_config({**default_config.DEFAULT_CONFIG, "data_cache_dir": str(tmp_path)})
    yield
    set_config(default_config.DEFAULT_CONFIG)


_AV_CSV = (
    "timestamp,open,high,low,close,volume\n"
    "2026-08-24,8749.60,8749.60,8593.55,8700.00,24334\n"
    "2026-08-21,8720.00,8743.35,8644.75,8659.00,314000\n"
)


@pytest.mark.unit
def test_converts_ns_and_bo_suffixes_to_bse():
    assert _to_alpha_vantage_symbol("APOLLOHOSP.NS") == "APOLLOHOSP.BSE"
    assert _to_alpha_vantage_symbol("APOLLOHOSP.BO") == "APOLLOHOSP.BSE"


@pytest.mark.unit
def test_symbols_with_no_known_alpha_vantage_equivalent_return_none():
    assert _to_alpha_vantage_symbol("BTC-USD") is None
    assert _to_alpha_vantage_symbol("CNC.TO") is None


@pytest.mark.unit
def test_load_ohlcv_from_alpha_vantage_parses_real_shape():
    with patch(
        "tradingagents.dataflows.alpha_vantage_stock.get_stock",
        return_value=_AV_CSV,
    ):
        result = _load_ohlcv_from_alpha_vantage("APOLLOHOSP.NS", "2026-08-01", "2026-08-25")

    assert result is not None
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert result.index.name == "Date"
    # Sorted ascending (Alpha Vantage returns newest-first).
    assert list(result.index) == sorted(result.index)
    assert result.loc[pd.Timestamp("2026-08-24"), "Close"] == 8700.00


@pytest.mark.unit
def test_load_ohlcv_from_alpha_vantage_returns_none_for_unconvertible_symbol():
    # No av_symbol -> never even calls get_stock.
    with patch("tradingagents.dataflows.alpha_vantage_stock.get_stock") as mock_get_stock:
        assert _load_ohlcv_from_alpha_vantage("BTC-USD", "2026-08-01", "2026-08-25") is None
    mock_get_stock.assert_not_called()


@pytest.mark.unit
def test_load_ohlcv_from_alpha_vantage_returns_none_on_malformed_response():
    # e.g. a JSON error body ("premium endpoint", rate limit) instead of CSV.
    with patch(
        "tradingagents.dataflows.alpha_vantage_stock.get_stock",
        return_value='{"Information": "rate limit"}',
    ):
        assert _load_ohlcv_from_alpha_vantage("APOLLOHOSP.NS", "2026-08-01", "2026-08-25") is None


@pytest.mark.unit
def test_load_ohlcv_recovers_via_alpha_vantage_when_yfinance_returns_nothing():
    empty = pd.DataFrame()
    # load_ohlcv now retries an empty yfinance result (retry_on_empty=True,
    # see stockstats_utils.yf_retry) before falling through to Alpha
    # Vantage, since an empty frame is throttling far more often than a
    # real "no data" answer. time.sleep is patched so the 3 retries this
    # induces (2s/4s/8s backoff) cost nothing in test time; the backoff
    # itself is asserted separately in test_yf_retry_on_empty.py.
    with patch("tradingagents.dataflows.stockstats_utils.yf.download", return_value=empty):
        with patch("tradingagents.dataflows.stockstats_utils.time.sleep"):
            with patch(
                "tradingagents.dataflows.alpha_vantage_stock.get_stock",
                return_value=_AV_CSV,
            ):
                result = load_ohlcv("APOLLOHOSP.NS", "2026-08-25")

    assert not result.empty
    assert "Date" in result.columns
    assert (result["Close"] == 8700.00).any()


@pytest.mark.unit
def test_load_ohlcv_still_raises_when_both_vendors_fail():
    empty = pd.DataFrame()
    with patch("tradingagents.dataflows.stockstats_utils.yf.download", return_value=empty):
        with patch("tradingagents.dataflows.stockstats_utils.time.sleep"):
            with patch(
                "tradingagents.dataflows.alpha_vantage_stock.get_stock",
                side_effect=ConnectionError("alpha vantage unreachable"),
            ):
                with pytest.raises(ValueError, match="yfinance returned no data"):
                    load_ohlcv("APOLLOHOSP.NS", "2026-08-25")


@pytest.mark.unit
def test_get_stock_uses_the_free_daily_endpoint_not_the_premium_adjusted_one():
    from tradingagents.dataflows.alpha_vantage_stock import get_stock

    with patch(
        "tradingagents.dataflows.alpha_vantage_stock._make_api_request",
        return_value=_AV_CSV,
    ) as mock_request:
        get_stock("APOLLOHOSP.BSE", "2026-08-01", "2026-08-25")

    function_arg = mock_request.call_args.args[0]
    assert function_arg == "TIME_SERIES_DAILY"
    assert function_arg != "TIME_SERIES_DAILY_ADJUSTED"
