"""Deterministic market-data validation snapshot builder."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from stockstats import wrap

from .stockstats_utils import (
    _prepare_ohlcv_for_wrap,
    load_ohlcv,
    normalize_indicator_value,
)

SNAPSHOT_INDICATORS = (
    "close_10_ema",
    "close_50_sma",
    "close_200_sma",
    "rsi",
    "macd",
    "macds",
    "macdh",
    "boll",
    "boll_ub",
    "boll_lb",
    "atr",
    "vwma",
    "mfi",
)

# Momentum/trend indicators where "is it rising or falling" changes the read
# — not the whole SNAPSHOT_INDICATORS list. The other indicators (SMAs/EMA,
# Bollinger bands, ATR, VWMA) are level-based: a single current value plus
# the Recent Closes table already lets an analyst judge them, and dumping a
# multi-day history for all 13 would recreate the exact bloat this snapshot
# exists to avoid — get_indicators's own default look_back_days=30 produced
# a full day-by-day series per indicator per tool call.
#
# This section exists specifically so get_indicators can be removed from
# market_analyst.py's LLM-callable tools without losing trend visibility:
# get_indicators returns day-by-day history (e.g. RSI for each of the last
# 30 days), which the snapshot previously did not — it gave only the single
# latest value per indicator, discarding exactly the "is RSI rising toward
# overbought" and "did MACD just cross its signal line" information a
# technical read depends on. Removing the tool without this section would
# have silently traded away real analytical capability for token savings.
TREND_INDICATORS = ("rsi", "macd", "macds", "macdh")

# Trading days of trend history shown per indicator. Short enough to stay
# compact (4 indicators x 10 values, one line each, vs get_indicators's full
# 30-day-per-call verbosity); long enough to show a crossover or a
# multi-session move toward/away from an overbought/oversold threshold.
TREND_WINDOW_DAYS = 10


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    """Build a deterministic OHLCV and indicator snapshot for a symbol.

    The returned report is intentionally compact and date-explicit so analyst
    prompts can treat it as the source of truth for exact price and indicator
    claims.
    """
    try:
        requested_date = datetime.strptime(curr_date, "%Y-%m-%d")
        look_back_days = max(int(look_back_days), 1)
        data = load_ohlcv(symbol, curr_date)
        if data.empty:
            return f"No verified market data found for {symbol.upper()} on or before {curr_date}"

        data = data.copy()
        data["Date"] = pd.to_datetime(data["Date"])
        data = data.sort_values("Date").reset_index(drop=True)
        latest = data.iloc[-1]
        latest_date = latest["Date"].strftime("%Y-%m-%d")
        recent = data.tail(look_back_days)
        indicators = _calculate_latest_indicators(data)
        trend = _calculate_trend_history(data, TREND_WINDOW_DAYS)

        lines = [
            f"## Verified Market Snapshot for {symbol.upper()}",
            f"Requested date: {curr_date}",
            f"Latest trading date used: {latest_date}",
            "",
            "### Latest OHLCV",
            f"Open: {_format_value(latest.get('Open'))}",
            f"High: {_format_value(latest.get('High'))}",
            f"Low: {_format_value(latest.get('Low'))}",
            f"Close: {_format_value(latest.get('Close'))}",
            f"Volume: {_format_value(latest.get('Volume'), decimals=0)}",
            "",
            "### Latest Indicators",
        ]
        lines.extend(
            f"{indicator}: {_format_value(value)}"
            for indicator, value in indicators.items()
        )

        if trend:
            trend_dates = trend[next(iter(trend))]["dates"]
            lines.extend(
                [
                    "",
                    f"### Indicator Trend ({len(trend_dates)} trading sessions, "
                    f"{trend_dates[0]} → {trend_dates[-1]}, oldest → newest)",
                ]
            )
            lines.extend(
                f"{indicator}: {', '.join(_format_value(v) for v in series['values'])}"
                for indicator, series in trend.items()
            )

        lines.extend(["", f"### Recent Closes ({len(recent)} trading rows)"])
        lines.extend(
            f"{row.Date.strftime('%Y-%m-%d')}: close={_format_value(row.Close)}, "
            f"volume={_format_value(getattr(row, 'Volume', None), decimals=0)}"
            for row in recent.itertuples(index=False)
        )

        if pd.Timestamp(latest["Date"]).date() < requested_date.date():
            lines.extend(
                [
                    "",
                    "Note: requested date was not an available trading row; "
                    "the latest prior trading date was used.",
                ]
            )

        return "\n".join(lines)
    except Exception as exc:
        return f"Error building verified market snapshot for {symbol}: {exc}"


def _calculate_latest_indicators(data: pd.DataFrame) -> dict[str, Any]:
    date_series, ohlcv = _prepare_ohlcv_for_wrap(data)
    stock_df = wrap(ohlcv)
    latest_idx = len(date_series) - 1

    indicators: dict[str, Any] = {}
    for indicator in SNAPSHOT_INDICATORS:
        try:
            values = stock_df[indicator]
            indicators[indicator] = normalize_indicator_value(
                indicator, values.iloc[latest_idx]
            )
        except Exception:
            indicators[indicator] = None
    return indicators


def _calculate_trend_history(data: pd.DataFrame, window_days: int) -> dict[str, dict[str, list]]:
    """Last ``window_days`` sessions of each :data:`TREND_INDICATORS` series.

    Returns ``{indicator: {"dates": [...], "values": [...]}}``, oldest first.
    Empty when there are no trading rows at all; a series shorter than
    ``window_days`` (early in a ticker's history) returns however many rows
    exist rather than padding or erroring.
    """
    if data.empty:
        return {}

    date_series, ohlcv = _prepare_ohlcv_for_wrap(data)
    stock_df = wrap(ohlcv)
    window = min(window_days, len(date_series))
    start_idx = len(date_series) - window

    trend: dict[str, dict[str, list]] = {}
    for indicator in TREND_INDICATORS:
        try:
            values = stock_df[indicator]
        except Exception:
            continue
        trend[indicator] = {
            "dates": list(date_series.iloc[start_idx:]),
            "values": [
                normalize_indicator_value(indicator, values.iloc[i])
                for i in range(start_idx, len(date_series))
            ],
        }
    return trend


def _format_value(value: Any, *, decimals: int = 4) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, (int, float)):
        if decimals == 0:
            return f"{value:,.0f}"
        return f"{value:,.{decimals}f}"
    return str(value)
