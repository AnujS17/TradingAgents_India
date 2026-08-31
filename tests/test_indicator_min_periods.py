"""An indicator must mean what its NAME says, or say that it cannot.

stockstats computes rolling windows with min_periods=1, so a "200 SMA" on a
stock with 199 sessions silently returns the mean of whatever exists rather
than NaN -- and the snapshot published that as authoritative.

PINELABS.NS 2026-08-31 (listed 2025-11-14, 199 sessions): close_200_sma came
back as 187.1495, which is EXACTLY the mean of all 199 available closes. The
stock IPO'd near 250 and had fallen to 165, so that "long-term average" was
really "average price since listing, dominated by the post-IPO decline". The
analyst then called 187 "the dominant overhead barrier ... the long-term
trend is still down" and turned it into a trade trigger: "Add only on a
confirmed daily close above 187 (200 SMA)" -- a fabricated level presented
as a technical one.
"""

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.market_data_validator import (
    _MIN_PERIODS,
    SNAPSHOT_INDICATORS,
    _calculate_latest_indicators,
)


def _ohlcv(rows: int) -> pd.DataFrame:
    """`rows` sessions of plausible, non-constant OHLCV."""
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1.5, rows))
    return pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=rows, freq="B"),
            "Open": close + rng.normal(0, 0.4, rows),
            "High": close + abs(rng.normal(1, 0.4, rows)),
            "Low": close - abs(rng.normal(1, 0.4, rows)),
            "Close": close,
            "Volume": rng.integers(1e5, 1e6, rows),
        }
    )


@pytest.mark.unit
def test_the_pinelabs_case_is_flagged_not_fabricated():
    """199 sessions, exactly PINELABS' history. The 200 SMA must refuse to
    answer; the 50 SMA has ample history and must still answer."""
    out = _calculate_latest_indicators(_ohlcv(199))

    assert isinstance(out["close_200_sma"], str)
    assert "not computable" in out["close_200_sma"]
    assert "199 available" in out["close_200_sma"]
    assert isinstance(out["close_50_sma"], float)


@pytest.mark.unit
def test_a_long_history_is_untouched():
    """KAYNES.NS has 935 sessions and its 200 SMA verified exactly against a
    hand-recomputed value -- this guard must not disturb that case."""
    out = _calculate_latest_indicators(_ohlcv(400))

    for name in SNAPSHOT_INDICATORS:
        assert not isinstance(out[name], str), f"{name} was suppressed with 400 sessions"


@pytest.mark.unit
@pytest.mark.parametrize("indicator,needed", sorted(_MIN_PERIODS.items()))
def test_each_windowed_indicator_refuses_one_row_short(indicator, needed):
    """Boundary in both directions: unavailable at needed-1, available at
    needed. Catches an off-by-one that would either fabricate a value or
    suppress a legitimate one."""
    short = _calculate_latest_indicators(_ohlcv(needed - 1))
    exact = _calculate_latest_indicators(_ohlcv(needed))

    assert isinstance(short[indicator], str), f"{indicator} fabricated at {needed - 1} rows"
    assert not isinstance(exact[indicator], str), f"{indicator} suppressed at {needed} rows"


@pytest.mark.unit
def test_exponential_indicators_are_never_suppressed():
    """The MACD family and the EMAs weight recent data and have no hard
    minimum window -- a short history makes them noisy, not meaningless.
    Suppressing them would remove real signal from a young listing, which is
    the opposite of the point."""
    out = _calculate_latest_indicators(_ohlcv(12))

    for name in ("close_10_ema", "macd", "macds", "macdh"):
        assert not isinstance(out[name], str), f"{name} should not be gated"


@pytest.mark.unit
def test_the_marker_survives_rendering():
    """_format_value must pass the marker through rather than choke on a
    non-numeric indicator value -- it reaches the model verbatim."""
    from tradingagents.dataflows.market_data_validator import _format_value

    out = _calculate_latest_indicators(_ohlcv(199))

    rendered = _format_value(out["close_200_sma"])
    assert "not computable" in rendered
