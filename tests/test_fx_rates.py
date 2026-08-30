from unittest.mock import patch

import pytest

from tradingagents.dataflows import fx_rates
from tradingagents.dataflows.fx_rates import FxRate, currency_mismatch_warning


@pytest.mark.unit
def test_no_warning_when_currencies_match():
    assert currency_mismatch_warning("USD", "USD") == ""


@pytest.mark.unit
def test_no_warning_when_currency_missing():
    assert currency_mismatch_warning(None, "USD") == ""
    assert currency_mismatch_warning("TWD", None) == ""
    assert currency_mismatch_warning("", "") == ""


@pytest.mark.unit
def test_warning_includes_live_rate_when_available():
    fake_rate = FxRate(from_currency="TWD", to_currency="USD", rate=0.0309, as_of="2026-06-01")
    with patch.object(fx_rates, "fetch_fx_rate", return_value=fake_rate):
        result = currency_mismatch_warning("TWD", "USD")

    assert "# Financial statement currency: TWD" in result
    assert "# Quote/price currency: USD" in result
    assert "1 TWD = 0.0309 USD" in result
    assert "as of 2026-06-01" in result
    assert "not converted to USD" in result


@pytest.mark.unit
def test_warning_notes_unavailable_rate_without_guessing():
    with patch.object(fx_rates, "fetch_fx_rate", return_value=None):
        result = currency_mismatch_warning("TWD", "USD")

    assert "# Financial statement currency: TWD" in result
    assert "could not be" in result
    assert "do not assume a 1:1 rate or invent a conversion" in result
    # Never fabricate a number when the live fetch failed.
    import re

    assert not re.search(r"1 TWD = [\d.]+ USD", result)


@pytest.mark.unit
def test_figures_description_is_used_in_final_sentence():
    fake_rate = FxRate(from_currency="TWD", to_currency="USD", rate=0.0309, as_of="2026-06-01")
    with patch.object(fx_rates, "fetch_fx_rate", return_value=fake_rate):
        result = currency_mismatch_warning("TWD", "USD", figures_description="raw financial statement values")

    assert "raw financial statement values" in result


@pytest.mark.unit
def test_fetch_fx_rate_degrades_gracefully_on_bad_pair():
    # lru_cache now lives on the private raw-fetch helper, not the public
    # function -- see the snapshot-cache split below.
    fx_rates._fetch_fx_rate_cached.cache_clear()
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.history.side_effect = Exception("no data")
        result = fx_rates.fetch_fx_rate("ZZZ", "USD")

    assert result is None


@pytest.mark.unit
def test_fetch_fx_rate_is_snapshot_cached_across_process_boundaries(tmp_path):
    """The point of this change: a same-day re-run (e.g. a different
    time_horizon) must replay the rate instead of hitting yfinance again."""
    from tradingagents.dataflows.config import get_config, set_config
    from tradingagents.dataflows.snapshot_cache import clear_snapshot_date, set_snapshot_date
    from tradingagents.default_config import DEFAULT_CONFIG

    fx_rates._fetch_fx_rate_cached.cache_clear()
    before = dict(get_config())
    set_config({**DEFAULT_CONFIG, "data_cache_dir": str(tmp_path)})
    set_snapshot_date("2026-08-28")
    calls = []
    try:
        with patch("yfinance.Ticker") as mock_ticker:
            import pandas as pd

            history = pd.DataFrame({"Close": [83.12]}, index=pd.to_datetime(["2026-08-28"]))
            mock_ticker.return_value.history.side_effect = lambda *a, **k: (calls.append(1), history)[1]

            first = fx_rates.fetch_fx_rate("USD", "INR")
            # A fresh interpreter shares no in-memory state -- clearing the
            # in-process memo stands in for a brand new run's process.
            fx_rates._fetch_fx_rate_cached.cache_clear()
            second = fx_rates.fetch_fx_rate("USD", "INR")
    finally:
        set_config(before)
        clear_snapshot_date()
        fx_rates._fetch_fx_rate_cached.cache_clear()

    assert first == second == FxRate(from_currency="USD", to_currency="INR", rate=83.12, as_of="2026-08-28")
    assert len(calls) == 1, "second call must be served from the snapshot cache, not yfinance"
