import time
import logging
from io import StringIO

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from stockstats import wrap
from typing import Annotated
import os
from .config import get_config
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)


def _is_empty_result(value) -> bool:
    """True for the several shapes yfinance uses to say "nothing"."""
    if value is None:
        return True
    empty = getattr(value, "empty", None)
    if empty is not None:
        return bool(empty)
    if isinstance(value, (list, tuple, dict, str)):
        return len(value) == 0
    return False


def yf_retry(func, max_retries=3, base_delay=2.0, retry_on_empty=False):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.

    ``retry_on_empty`` additionally retries a call that SUCCEEDS but hands
    back nothing. Under sustained load yfinance's informal API usually
    throttles by returning an empty frame rather than raising 429 (see
    PERF_HANDOFF.md: "yfinance's informal API throttles hard under sustained
    request volume"), so the 429-only path above never fired for the failure
    mode that actually happens. PINELABS.NS and LENSKART.NS both lost their
    verified market snapshot to this on 2026-08-26/27 -- "yfinance returned
    no data" -- and both fetch fine on retry, which is what identifies it as
    throttling rather than a bad symbol.

    OFF by default because empty is a legitimate answer for most callers: a
    news search with no hits, a statement a company has not filed, a young
    listing with no history for a window. Retrying those would burn the
    backoff on a result that will never change. Enabled only where empty
    genuinely means failure -- price history for a live symbol.
    """
    for attempt in range(max_retries + 1):
        try:
            result = func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            raise
        if retry_on_empty and _is_empty_result(result) and attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Yahoo Finance returned no data (likely throttling), retrying in "
                "%.0fs (attempt %d/%d)", delay, attempt + 1, max_retries,
            )
            time.sleep(delay)
            continue
        return result


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


# yfinance's own suffix convention (.NS/.BO) has no Alpha Vantage
# equivalent -- Alpha Vantage's global-equity coverage for NSE/BSE names
# is BSE-only, under a single ".BSE" suffix (confirmed live: querying
# "APOLLOHOSP.NS" against TIME_SERIES_DAILY returns nothing; "APOLLOHOSP.BSE"
# returns real current data). Both yfinance suffixes map to it.
_YFINANCE_TO_ALPHA_VANTAGE_SUFFIX = {".NS": ".BSE", ".BO": ".BSE"}


def _to_alpha_vantage_symbol(symbol: str) -> str | None:
    """Convert a yfinance-suffixed symbol to Alpha Vantage's form, or None
    if this symbol has no known Alpha Vantage equivalent (anything not
    NSE/BSE-suffixed -- the fallback below only ever applies to Indian
    equities, the same scope resolve_ticker_symbol resolves)."""
    for yf_suffix, av_suffix in _YFINANCE_TO_ALPHA_VANTAGE_SUFFIX.items():
        if symbol.endswith(yf_suffix):
            return symbol[: -len(yf_suffix)] + av_suffix
    return None


def _load_ohlcv_from_alpha_vantage(symbol: str, start_str: str, end_str: str) -> "pd.DataFrame | None":
    """Fallback OHLCV source for when yfinance fails outright (empty
    download, a 401/blocked response, or any other total miss -- see
    load_ohlcv's caller). APOLLOHOSP.NS, 2026-08-25: yfinance returned a
    401 "User is unable to access this feature" followed by "possibly
    delisted", the deterministic Verified Market Snapshot failed
    entirely, and the Market Analyst had to reconstruct a technical read
    through its own get_stock_data tool call instead -- costing an 8-minute
    gap in the run while that recovery happened. This gives the snapshot
    itself the same fallback get_stock_data already had (route_to_vendor's
    alpha_vantage vendor), so a yfinance outage degrades in seconds, not
    minutes, and the "source of truth" snapshot the prompts tell every
    analyst to trust doesn't stay silently broken while a side-channel
    tool call quietly does the real work.

    Returns None (never raises) for anything this fallback can't help
    with -- an unconvertible symbol, a request error, an empty or
    malformed response -- so the caller falls through to its own "no
    data" error instead of masking it with an unrelated Alpha Vantage
    traceback.
    """
    av_symbol = _to_alpha_vantage_symbol(symbol)
    if av_symbol is None:
        return None

    from .alpha_vantage_stock import get_stock

    try:
        csv_text = get_stock(av_symbol, start_str, end_str)
        parsed = pd.read_csv(StringIO(csv_text))
    except Exception as exc:  # noqa: BLE001 — any failure here just means "no fallback available"
        logger.debug("Alpha Vantage OHLCV fallback failed for %s (%s): %s", symbol, av_symbol, exc)
        return None

    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(parsed.columns) or parsed.empty:
        logger.debug(
            "Alpha Vantage OHLCV fallback for %s (%s) returned no usable rows",
            symbol, av_symbol,
        )
        return None

    parsed = parsed.rename(columns={
        "timestamp": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    })
    parsed["Date"] = pd.to_datetime(parsed["Date"])
    parsed = parsed.sort_values("Date").set_index("Date")
    return parsed[["Open", "High", "Low", "Close", "Volume"]]


# Fallback for the recheck window when no config is loaded (bare programmatic
# use, tests). The live value is config["ohlcv_cache_recheck_seconds"]; see
# default_config.py for what it bounds and why.
_STALE_CACHE_RECHECK_SECONDS = 30 * 60


def _cache_date_extents(data_file: str) -> "tuple[pd.Timestamp | None, pd.Timestamp | None]":
    """``(newest row with a Close, newest row of any kind)`` from the cache.

    Both are needed because they answer different questions, and the gap
    between them is itself the signal that matters.

    Deliberately not "the newest date in the file": yfinance publishes a
    partially-consolidated bar for the current session, with a real date and
    volume but Open/High/Low/Close all NaN. ITC.NS 2026-09-02 cached exactly
    that --

        2026-08-31,255.5,266.55,255.5,266.0,24575845
        2026-09-01,,,,,31232541        <- date + volume, no prices

    -- and a date-only freshness check reads the 09-01 row as "the vendor has
    published that session", when the row is unusable and gets dropped a few
    lines later by the dropna(subset=["Close"]) in get_stock_stats. The run
    then analysed 08-31 prices while the stock had closed 4.3% higher on
    09-01, and recommended an entry that was never fillable.

    Reading Close (not just Date) is what makes the freshness question
    "has the vendor published a USABLE bar for that session", which is the
    question the caller actually needs answered. And when the two disagree
    -- a dated row newer than the newest priced one -- that is positive
    evidence the vendor is already publishing a session we hold only as an
    unusable stub, which is a stronger signal than any elapsed-time guess.
    """
    try:
        frame = pd.read_csv(
            data_file,
            usecols=lambda c: str(c).strip().lower() in ("date", "index", "close"),
            on_bad_lines="skip",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable cache is a refetch
        logger.warning("Could not read cache %s (%s); refetching", data_file, exc)
        return None, None

    if frame.empty:
        return None, None

    cols = {str(c).strip().lower(): c for c in frame.columns}
    date_col = cols.get("date") or cols.get("index")
    close_col = cols.get("close")
    if date_col is None:
        return None, None

    dates = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
    newest_dated = dates.dropna()
    newest_dated = newest_dated.max().tz_localize(None) if not newest_dated.empty else None

    # No Close column at all is a shape we cannot vet -- report the date-only
    # answer for both rather than forcing a refetch on every call.
    if close_col is None:
        return newest_dated, newest_dated

    priced = dates[pd.to_numeric(frame[close_col], errors="coerce").notna()].dropna()
    newest_priced = priced.max().tz_localize(None) if not priced.empty else None
    return newest_priced, newest_dated


def _cache_covers_date(data_file: str, curr_date_dt: pd.Timestamp) -> bool:
    """Is this cache file new enough to answer for ``curr_date``?

    load_ohlcv keys its cache on (symbol, today) and reuses it for the whole
    day, which silently pins a run to whatever the vendor had published at
    the FIRST fetch of that day. KAYNES.NS 2026-08-31: a run at 16:38 IST --
    an hour after the 15:30 close -- wrote a cache whose last row was
    2026-08-28, because yfinance had not yet published the 08-31 bar. Every
    later run that day reused it, so a 19:51 IST run analysed three-day-old
    prices and never saw a -6.5% session (3943 -> 3685). The file was
    byte-identical to the previous day's, which is how it went unnoticed.

    Returns True (use the cache) when it already contains a PRICED row on or
    after curr_date, and when it does not but was written recently enough
    that re-asking would just re-confirm the same answer. Returns False to
    force a refetch. Any read failure returns False -- refetching is always
    safe, trusting an unreadable cache is not.

    Freshness checking as a whole is gated by
    config["ohlcv_cache_freshness_check"]; when that is off the caller never
    reaches here and the cache is reused for the whole day (the original
    behaviour, and the one both stale-price incidents ran on).
    """
    try:
        newest_priced, newest_dated = _cache_date_extents(data_file)
        if newest_priced is None:
            return False
        if newest_priced >= curr_date_dt:
            return True
        if newest_dated is not None and newest_dated > newest_priced:
            # The vendor has already published a session we only hold as a
            # price-less stub (ITC.NS 2026-09-01: date + volume, OHLC all
            # NaN). Waiting out the recheck window here would serve prices we
            # already know to be behind -- refetch now, not in 30 minutes.
            logger.info(
                "Cache %s holds an unpriced %s row; refetching for %s",
                os.path.basename(data_file),
                newest_dated.date(),
                curr_date_dt.date(),
            )
            return False
        recheck_seconds = get_config().get(
            "ohlcv_cache_recheck_seconds", _STALE_CACHE_RECHECK_SECONDS
        )
        age = time.time() - os.path.getmtime(data_file)
        return age < recheck_seconds
    except Exception as exc:  # noqa: BLE001 - a bad cache is a refetch, not an error
        logger.warning("Could not date-check cache %s (%s); refetching", data_file, exc)
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

    # Freshness checking is opt-out (config["ohlcv_cache_freshness_check"]).
    # Off means "the file exists, so use it" for the rest of the day --
    # exactly the behaviour that let KAYNES.NS and ITC.NS analyse days-old
    # prices. See default_config.py for both incidents.
    freshness_on = get_config().get("ohlcv_cache_freshness_check", True)
    if os.path.exists(data_file) and (
        not freshness_on or _cache_covers_date(data_file, curr_date_dt)
    ):
        data = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
    else:
        # retry_on_empty: price history for a live symbol coming back empty
        # is throttling far more often than it is a real "no such data"
        # answer, and the Alpha Vantage fallback below is a much more
        # expensive way to discover that (free-tier quota, different
        # coverage). Retry the cheap source before escalating.
        raw = yf_retry(lambda: yf.download(
            symbol,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ), retry_on_empty=True)

        if raw is None or raw.empty:
            fallback = _load_ohlcv_from_alpha_vantage(symbol, start_str, end_str)
            if fallback is not None and not fallback.empty:
                logger.warning(
                    "yfinance returned no data for %s; recovered via Alpha Vantage fallback",
                    symbol,
                )
                raw = fallback
            elif os.path.exists(data_file):
                # We only got here because the cache did not reach curr_date,
                # and now the vendors cannot better it. Stale data beats no
                # data: before the freshness check existed this same cache
                # would have been served without question, so falling back
                # to it is the previous behaviour, not a new risk. Loudly
                # logged because a run built on it is reading old prices.
                logger.warning(
                    "%s: no fresh vendor data; falling back to the existing "
                    "cache, which does not reach %s",
                    symbol, curr_date,
                )
                data = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
                raw = None
                # Reset the staleness clock so a vendor that has simply not
                # published yet is re-asked on a schedule rather than on
                # every single call for the rest of the day.
                os.utime(data_file, None)
            else:
                raise ValueError(
                    f"yfinance returned no data for '{symbol}' "
                    f"({start_str} – {end_str}). Check the ticker symbol and network."
                )

        # raw is None only on the stale-cache fallback above, where `data`
        # is already loaded and must not be re-derived or re-written.
        if raw is not None:
            # Force index.name = "Date" before reset_index() so that the
            # resulting column is always called 'Date' regardless of
            # yfinance version.
            if raw.index.name != "Date":
                raw.index.name = "Date"
            data = raw.reset_index()

            # Belt-and-suspenders: normalise in case some yfinance version
            # still produces a different name after the above assignment.
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
