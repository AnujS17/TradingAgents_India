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

# Trading rows an indicator needs before its value means what its NAME says.
#
# stockstats computes rolling windows with min_periods=1, so a "200 SMA" on a
# stock with 199 sessions silently returns the mean of whatever exists rather
# than NaN -- and we published that as an authoritative indicator.
#
# PINELABS.NS 2026-08-31 (listed 2025-11-14, 199 sessions): the snapshot
# reported close_200_sma = 187.1495, which is EXACTLY the mean of all 199
# available closes. Because the stock IPO'd near 250 and had fallen to 165,
# that "long-term average" was really "average price since listing, dominated
# by the post-IPO decline" -- and the analyst built a thesis on it, calling
# 187 "the dominant overhead barrier ... the long-term trend is still down"
# and turning it into a trade trigger: "Add only on a confirmed daily close
# above 187 (200 SMA)". A fabricated level presented as a technical one.
#
# Only window-defined indicators appear here. The MACD family and the EMAs
# are exponential: they weight recent data and have no hard minimum, so a
# short history makes them noisy rather than meaningless, and dropping them
# would remove real signal. Indicators absent from this map are always kept.
_MIN_PERIODS = {
    "close_50_sma": 50,
    "close_200_sma": 200,
    "boll": 20,
    "boll_ub": 20,
    "boll_lb": 20,
    "vwma": 20,
    "rsi": 14,
    "atr": 14,
    "mfi": 14,
}

# Rendered in place of the value, so the model SEES that the indicator was
# unavailable and can caveat it, instead of the row silently vanishing and
# leaving it to assume the data simply was not requested. Mirrors the
# fundamentals analyst's "<block unavailable: ...>" markers, and matches how
# deepseek's own PINELABS run handled it when its snapshot failed outright:
# "close_200_sma: Not computable from available data".
_INSUFFICIENT_HISTORY = "not computable (needs {needed} sessions, {have} available)"

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

        latest_ts = pd.Timestamp(latest["Date"])
        if latest_ts.date() < requested_date.date():
            # Weekday count, not calendar days: a Friday bar read on Monday
            # misses nothing, while ITC.NS's Monday 08-31 bar read on
            # Wednesday 09-02 misses a full session -- the one in which the
            # stock rose 4.3%.
            # requested_date arrives as a datetime.datetime, not a Timestamp
            # -- normalize() is a Timestamp method, so it must be wrapped.
            missed = max(0, len(pd.bdate_range(
                latest_ts.normalize(),
                pd.Timestamp(requested_date).normalize(),
            )) - 2)
            if missed:
                # The old text here ("the latest prior trading date was
                # used") was true and useless: it reads as routine
                # weekend/holiday handling, so every downstream agent
                # ignored it. ITC.NS 2026-09-02 is what that cost -- the
                # snapshot quoted the 08-31 close of 255.50 while the news
                # report in the SAME run led with "ITC Rallies 4.3%" dated
                # 09-01, and not one agent reconciled the two. The bull even
                # cited the rally as a catalyst while endorsing an entry at
                # the pre-rally price.
                #
                # Naming the number of missed sessions, and pointing at the
                # news reports as the cross-check, is what turns this from a
                # footnote into something an agent can act on.
                session_word = "session falls" if missed == 1 else "sessions fall"
                lines.extend([
                    "",
                    f"**STALENESS WARNING: this snapshot is behind.** The latest "
                    f"row is {latest_ts.strftime('%Y-%m-%d')}, but roughly "
                    f"{missed} trading {session_word} between it and the "
                    f"requested date of {curr_date}. The vendor had not "
                    "published those bars when this ran, so every price and "
                    "indicator above predates them.",
                    "",
                    "Act on this: if the news or sentiment reports mention a "
                    f"price move after {latest_ts.strftime('%Y-%m-%d')}, the "
                    "live price is NOT the close shown above and you must say "
                    "so. Do not present these levels as current, and do not "
                    "propose an entry, stop or exit that only makes sense at "
                    "the stale price.",
                ])
            else:
                lines.extend([
                    "",
                    "Note: the requested date was not an available trading row "
                    "(weekend or holiday); the latest prior trading date was "
                    "used. No trading session was missed.",
                ])

        return "\n".join(lines)
    except Exception as exc:
        return f"Error building verified market snapshot for {symbol}: {exc}"


def _calculate_latest_indicators(data: pd.DataFrame) -> dict[str, Any]:
    date_series, ohlcv = _prepare_ohlcv_for_wrap(data)
    stock_df = wrap(ohlcv)
    latest_idx = len(date_series) - 1

    available = len(date_series)

    indicators: dict[str, Any] = {}
    for indicator in SNAPSHOT_INDICATORS:
        needed = _MIN_PERIODS.get(indicator)
        if needed is not None and available < needed:
            indicators[indicator] = _INSUFFICIENT_HISTORY.format(
                needed=needed, have=available
            )
            continue
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
