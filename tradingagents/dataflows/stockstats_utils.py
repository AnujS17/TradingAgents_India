import time
import logging

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from stockstats import wrap
from typing import Annotated
import os
from .config import get_config
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise


# ──────────────────────────────────────────────────────────────────────────────
# ROOT CAUSE FIX (v2 — handles empty DataFrames too)
# ──────────────────────────────────────────────────────────────────────────────
# yfinance >= 0.2.x with `multi_level_index=False` returns a DatetimeIndex
# whose .name is None.  After reset_index() that becomes a column called
# 'index' rather than 'Date'.
#
# The GPT-suggested v1 fix validated dates on a sample before renaming, which
# silently broke when the DataFrame was EMPTY (e.g. a failed download).
# An empty 'index' column has no sample → len(sample)==0 → rename never fires
# → KeyError: 'Date' propagates → LLM hallucinates all technical data.
#
# v2 fixes:
#   1. _normalise_date_column: rename 'index'/'Datetime' unconditionally when
#      DataFrame is empty; keep date-validation only for non-empty frames where
#      we must distinguish an integer index column from a date column.
#   2. load_ohlcv: never cache an empty download; stale cache files that lack
#      a recognisable date column are deleted and re-downloaded.
#   3. load_ohlcv: force index.name = "Date" before reset_index() so that fresh
#      downloads always write a clean 'Date' column — no rename needed at all.
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Rename the date column to 'Date' regardless of what yfinance called it.

    Handles all column-name variants yfinance may produce:
      'Date'     – already correct, return immediately
      'Datetime' – intraday data
      'datetime' – lower-case variant
      'index'    – reset_index() on a DatetimeIndex with name=None

    For non-empty DataFrames a quick date-parse sanity check guards against
    accidentally renaming an integer index column.  For empty DataFrames the
    check is skipped (no rows to sample) and the rename is done by column name
    alone — this is the critical v1 regression fix.
    """
    if "Date" in data.columns:
        return data

    for candidate in ("Datetime", "datetime", "index"):
        if candidate in data.columns:
            if data.empty:
                # No rows to validate — trust the column name.
                return data.rename(columns={candidate: "Date"})
            sample = data[candidate].dropna().iloc[:1]
            if len(sample) and pd.to_datetime(sample, errors="coerce").notna().all():
                return data.rename(columns={candidate: "Date"})

    # Last resort: if the caller forgot reset_index() and Date is still the index
    if isinstance(data.index, pd.DatetimeIndex) or data.index.name in (
        "Date", "Datetime", "datetime"
    ):
        idx_name = data.index.name or "Date"
        return (
            data.rename_axis(None)
            .reset_index()
            .rename(columns={"index": "Date", idx_name: "Date"})
        )

    return data  # unable to locate a date column — caller will raise clearly


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data = _normalise_date_column(data)  # ← normalise BEFORE accessing data["Date"]

    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


def _cache_is_valid(data_file: str) -> bool:
    """Return True only if the cached CSV contains a usable date column."""
    try:
        header = pd.read_csv(data_file, nrows=0)
        # Accept any of the known date column names
        return bool({"Date", "Datetime", "datetime", "index"} & set(header.columns))
    except Exception:
        return False


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 5 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused unless it is invalid. Rows after
    curr_date are filtered out so backtests never see future prices.

    Key invariant: the returned DataFrame always has a 'Date' column.
    """
    safe_symbol = safe_ticker_component(symbol)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    # Invalidate stale caches that are missing a recognisable date column
    if os.path.exists(data_file) and not _cache_is_valid(data_file):
        logger.warning(f"Stale/corrupt cache detected for {symbol}, deleting: {data_file}")
        try:
            os.remove(data_file)
        except OSError as e:
            logger.error(f"Could not remove stale cache {data_file}: {e}")

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
    else:
        raw = yf_retry(lambda: yf.download(
            symbol,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))

        if raw is None or raw.empty:
            raise ValueError(
                f"yfinance returned no data for '{symbol}' "
                f"({start_str} – {end_str}). Check the ticker symbol and network."
            )

        # Force index.name = "Date" before reset_index() so that the resulting
        # column is always called 'Date' regardless of yfinance version.
        if raw.index.name != "Date":
            raw.index.name = "Date"
        data = raw.reset_index()

        # Belt-and-suspenders: normalise in case some yfinance version still
        # produces a different name after the above assignment.
        data = _normalise_date_column(data)

        # Only cache non-empty, valid data
        if not data.empty and "Date" in data.columns:
            data.to_csv(data_file, index=False, encoding="utf-8")
        else:
            logger.warning(f"Skipping cache write for {symbol}: data invalid after normalisation")

    data = _clean_dataframe(data)

    # Ensure Date column exists and reset index if it's the index
    if data.index.name == "Date":
        data = data.reset_index()

    # Filter to curr_date to prevent look-ahead bias in backtesting
    data = data[data["Date"] <= curr_date_dt]

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


# stockstats returns MFI as a 0–1 ratio, but every standard MFI definition —
# and the overbought/oversold guidance shipped in our own indicator
# descriptions ("overbought >80", "oversold <20") — is stated on a 0–100
# scale, exactly like the RSI printed beside it. Emitting the raw ratio put a
# value of 0.9224 next to a ">80 means overbought" rubric, which reads as
# deeply *oversold* when the true reading is 92 (deeply overbought) — an
# inversion that also flatly contradicted the RSI of 81.9 in the same
# snapshot. Scaling here keeps the two momentum oscillators on one scale so
# the LLM cannot draw the opposite conclusion from correctly-fetched data.
# (Found auditing the LAURUSLABS.BO snapshot, 2026-08-10.)
_PERCENT_SCALE_INDICATORS = {"mfi"}


def normalize_indicator_value(indicator: str, value):
    """Rescale ratio-scaled stockstats indicators onto their conventional range."""
    if indicator not in _PERCENT_SCALE_INDICATORS or value is None:
        return value
    try:
        if pd.isna(value):
            return value
        return float(value) * 100.0
    except (TypeError, ValueError):
        return value


def _prepare_ohlcv_for_wrap(data: pd.DataFrame):
    """Sort by date; return (date_series, ohlcv_df) ready for stockstats.wrap().

    Keeps the date information as a plain pandas Series (int-indexed, same
    positional order as the returned ohlcv_df) so callers can map indicator
    values back to dates without injecting 'Date' into the StockDataFrame.
    """
    data = data.copy()
    data["Date"] = pd.to_datetime(data["Date"])
    data = data.sort_values("Date").reset_index(drop=True)

    date_series = data["Date"].dt.strftime("%Y-%m-%d")  # pd.Series with int index 0..N-1

    ohlcv_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    ohlcv = data[ohlcv_cols].copy()

    return date_series, ohlcv


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        try:
            data = load_ohlcv(symbol, curr_date)

            if "Date" not in data.columns:
                if data.index.name == "Date" or isinstance(data.index, pd.DatetimeIndex):
                    data = data.reset_index()
                else:
                    raise KeyError(f"Date column not found. Columns: {data.columns.tolist()}")

            date_series, ohlcv = _prepare_ohlcv_for_wrap(data)
            df = wrap(ohlcv)

            # Trigger lazy indicator calculation
            _ = df[indicator]

            curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")
            matching_idx = date_series[date_series == curr_date_str].index

            if matching_idx.empty:
                return "N/A: Not a trading day (weekend or holiday)"

            indicator_value = df.loc[matching_idx[0], indicator]
            return indicator_value

        except Exception as e:
            logger.error(f"Error in get_stock_stats: {e}", exc_info=True)
            raise
