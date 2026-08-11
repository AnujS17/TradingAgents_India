import pandas as pd
import pytest

from tradingagents.dataflows.market_data_validator import (
    TREND_INDICATORS,
    TREND_WINDOW_DAYS,
    build_verified_market_snapshot,
)


def _sample_ohlcv():
    return pd.DataFrame(
        {
            "Date": pd.date_range("2026-04-01", periods=60, freq="B"),
            "Open": [100 + i for i in range(60)],
            "High": [101 + i for i in range(60)],
            "Low": [99 + i for i in range(60)],
            "Close": [100.5 + i for i in range(60)],
            "Volume": [1_000_000 + (i * 1000) for i in range(60)],
        }
    )


@pytest.mark.unit
def test_build_verified_market_snapshot_uses_latest_available_row(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.market_data_validator.load_ohlcv",
        lambda symbol, curr_date: _sample_ohlcv(),
    )

    result = build_verified_market_snapshot("MSFT", "2026-07-10", look_back_days=3)

    assert "Verified Market Snapshot for MSFT" in result
    assert "Latest trading date used: 2026-06-23" in result
    assert "Close: 159.5000" in result
    assert "close_50_sma:" in result
    assert result.count("close=") == 3


@pytest.mark.unit
def test_snapshot_includes_indicator_trend_section(monkeypatch):
    # This section exists so get_indicators can be removed from
    # market_analyst.py's LLM-callable tools without losing trend visibility
    # (RSI rising toward overbought, a MACD/signal crossover) that a single
    # latest-value-only snapshot cannot show.
    monkeypatch.setattr(
        "tradingagents.dataflows.market_data_validator.load_ohlcv",
        lambda symbol, curr_date: _sample_ohlcv(),
    )

    result = build_verified_market_snapshot("MSFT", "2026-07-10", look_back_days=3)

    assert "### Indicator Trend" in result
    for indicator in TREND_INDICATORS:
        assert f"\n{indicator}: " in result


def _trend_section(result: str) -> list[str]:
    """Lines belonging to the '### Indicator Trend' section only.

    'rsi: ...' appears in BOTH '### Latest Indicators' (a single value) and
    '### Indicator Trend' (the multi-session series) — scanning the whole
    result for the first 'rsi: ' match silently grabs the wrong section.
    """
    lines = result.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("### Indicator Trend"))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")),
        len(lines),
    )
    return lines[start:end]


@pytest.mark.unit
def test_trend_section_shows_configured_window_of_sessions(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.market_data_validator.load_ohlcv",
        lambda symbol, curr_date: _sample_ohlcv(),
    )

    result = build_verified_market_snapshot("MSFT", "2026-07-10", look_back_days=3)

    section = _trend_section(result)
    trend_line = next(line for line in section if line.startswith(f"{TREND_INDICATORS[0]}: "))
    values = trend_line.split(": ", 1)[1].split(", ")
    assert len(values) == TREND_WINDOW_DAYS
    assert f"({TREND_WINDOW_DAYS} trading sessions" in result


@pytest.mark.unit
def test_trend_dates_are_oldest_first():
    # Test the ordering guarantee directly against the dates
    # _calculate_trend_history returns, rather than against a real
    # indicator's computed values: RSI is a momentum oscillator and can
    # legitimately dip during an overall uptrend on a local pullback, so
    # "prices are rising -> RSI values must increase left-to-right" is not a
    # sound premise to test against. Date ordering is unambiguous.
    from tradingagents.dataflows.market_data_validator import _calculate_trend_history

    trend = _calculate_trend_history(_sample_ohlcv(), TREND_WINDOW_DAYS)

    dates = trend[TREND_INDICATORS[0]]["dates"]
    assert dates == sorted(dates)
    assert dates[0] < dates[-1]


@pytest.mark.unit
def test_trend_values_align_positionally_with_their_dates():
    # The values list and dates list must be the same length and in lockstep
    # — a length mismatch would silently mislabel every value in the
    # rendered "rsi: v1, v2, ..." line against the header's date range.
    from tradingagents.dataflows.market_data_validator import _calculate_trend_history

    trend = _calculate_trend_history(_sample_ohlcv(), TREND_WINDOW_DAYS)

    for indicator, series in trend.items():
        assert len(series["dates"]) == len(series["values"])


@pytest.mark.unit
def test_trend_window_shrinks_gracefully_on_short_history():
    # Early in a ticker's listed history there may be fewer rows than
    # TREND_WINDOW_DAYS; this must return what's available, not error or pad.
    short_df = pd.DataFrame(
        {
            "Date": pd.date_range("2026-07-01", periods=4, freq="B"),
            "Open": [100, 101, 102, 103],
            "High": [101, 102, 103, 104],
            "Low": [99, 100, 101, 102],
            "Close": [100.5, 101.5, 102.5, 103.5],
            "Volume": [1_000_000] * 4,
        }
    )
    import tradingagents.dataflows.market_data_validator as mdv

    original = mdv.load_ohlcv
    mdv.load_ohlcv = lambda symbol, curr_date: short_df
    try:
        result = build_verified_market_snapshot("MSFT", "2026-07-06", look_back_days=3)
    finally:
        mdv.load_ohlcv = original

    assert "Error" not in result
    rsi_line = next(line for line in _trend_section(result) if line.startswith("rsi: "))
    values = rsi_line.split(": ", 1)[1].split(", ")
    assert len(values) <= 4
