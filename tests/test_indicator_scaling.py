"""Indicator scale-normalisation tests.

stockstats returns MFI as a 0–1 ratio while every standard definition — and
the overbought/oversold guidance shipped alongside it ("overbought >80",
"oversold <20") — is stated on 0–100. The raw ratio therefore inverted the
signal: the LAURUSLABS.BO snapshot printed `mfi: 0.9224` beside `rsi:
81.9118`, so an LLM applying the documented rubric would read a deeply
overbought instrument (92) as deeply oversold, in direct contradiction of
the RSI immediately above it.
"""

import pandas as pd
import pytest

from tradingagents.dataflows.stockstats_utils import normalize_indicator_value


@pytest.mark.unit
def test_mfi_is_rescaled_to_percent():
    assert normalize_indicator_value("mfi", 0.9224) == pytest.approx(92.24)


@pytest.mark.unit
def test_mfi_lands_in_same_range_as_rsi():
    # The whole point: both momentum oscillators must be comparable on sight.
    assert 0 <= normalize_indicator_value("mfi", 0.034) <= 100
    assert 0 <= normalize_indicator_value("mfi", 0.969) <= 100


@pytest.mark.unit
@pytest.mark.parametrize("indicator", ["rsi", "close_50_sma", "macd", "atr", "vwma"])
def test_other_indicators_are_untouched(indicator):
    # Only ratio-scaled indicators are adjusted; rescaling a price-scale
    # indicator would corrupt it.
    assert normalize_indicator_value(indicator, 81.9118) == 81.9118


@pytest.mark.unit
def test_nan_and_none_pass_through():
    assert normalize_indicator_value("mfi", None) is None
    assert pd.isna(normalize_indicator_value("mfi", float("nan")))


@pytest.mark.unit
def test_non_numeric_value_passes_through():
    assert normalize_indicator_value("mfi", "N/A") == "N/A"


@pytest.mark.unit
def test_snapshot_reports_mfi_on_percent_scale(monkeypatch):
    """End-to-end through the verified snapshot the market analyst is given."""
    from tradingagents.dataflows import market_data_validator as mdv

    rows = 60
    frame = pd.DataFrame(
        {
            "Date": pd.date_range("2026-05-01", periods=rows, freq="D"),
            "Open": [100.0 + i for i in range(rows)],
            "High": [101.0 + i for i in range(rows)],
            "Low": [99.0 + i for i in range(rows)],
            "Close": [100.5 + i for i in range(rows)],
            "Volume": [1_000 + 10 * i for i in range(rows)],
        }
    )
    monkeypatch.setattr(mdv, "load_ohlcv", lambda symbol, curr_date: frame)

    snapshot = mdv.build_verified_market_snapshot("TEST.NS", "2026-06-29", 5)

    mfi_line = next(l for l in snapshot.splitlines() if l.startswith("mfi:"))
    mfi_value = float(mfi_line.split(":")[1].strip().replace(",", ""))
    # Steadily rising series => strong money flow => high MFI on 0–100.
    assert mfi_value > 1.0, f"MFI still on 0-1 ratio scale: {mfi_line}"
    assert mfi_value <= 100.0
