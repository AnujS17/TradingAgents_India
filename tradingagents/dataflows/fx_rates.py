"""Live FX rate fetcher, used when a ticker's financial-statement currency
differs from its quote currency (see y_finance.py's currency-mismatch check).

Uses yfinance's own FX-pair ticker convention (``"{FROM}{TO}=X"``), so no new
API key or vendor is introduced — yfinance is already a hard dependency and
already the primary vendor for this codebase.

Deliberately NOT implemented as "ask the LLM to fetch the rate": none of the
analysts have a web-browsing tool, and instructing an ungrounded LLM to pull
a number from the open web is a well-known hallucination trigger. Fetching
it deterministically here and handing the LLM the real number is safer and
matches how every other cross-checkable fact already flows through this
codebase (see get_verified_market_snapshot for the same rationale).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Optional

from .snapshot_cache import snapshot_cached

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FxRate:
    from_currency: str
    to_currency: str
    rate: float
    as_of: str  # YYYY-MM-DD, the trading date the rate was quoted on


@lru_cache(maxsize=64)
@snapshot_cached("fx_rate")
def _fetch_fx_rate_cached(from_currency: str, to_currency: str) -> Optional[tuple[float, str]]:
    """Raw fetch, split out so the cache stores a plain (rate, as_of) tuple --
    FxRate itself is a dataclass, which snapshot_cached's JSON persistence
    cannot serialise. Returns None for "no rows" (a real, cacheable answer,
    same as an empty news search); raises on failure so a transient error
    is never the thing that gets frozen for the rest of the day.
    """
    import yfinance as yf

    pair = yf.Ticker(f"{from_currency}{to_currency}=X")
    history = pair.history(period="5d")
    closes = history["Close"].dropna()
    if closes.empty:
        return None
    rate = float(closes.iloc[-1])
    as_of = closes.index[-1]
    as_of_str = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)
    return (rate, as_of_str)


def fetch_fx_rate(from_currency: str, to_currency: str) -> Optional[FxRate]:
    """Fetch the live ``from_currency`` -> ``to_currency`` rate.

    Returns None (never raises) if the pair can't be resolved — a bad/rare
    currency code, no network, or yfinance returning no rows. Snapshot-cached
    per (ticker pair, analysis date): a same-day rate lookup doesn't need to
    be repeated across every fundamentals call in a single run, or across a
    same-day re-run with a different time horizon.
    """
    from_currency = (from_currency or "").upper().strip()
    to_currency = (to_currency or "").upper().strip()
    if not from_currency or not to_currency or from_currency == to_currency:
        return None

    try:
        result = _fetch_fx_rate_cached(from_currency, to_currency)
    except Exception as exc:
        logger.warning("FX rate fetch failed for %s->%s: %s", from_currency, to_currency, exc)
        return None

    if result is None:
        logger.warning("No FX history returned for %s->%s", from_currency, to_currency)
        return None
    rate, as_of_str = result
    return FxRate(from_currency=from_currency, to_currency=to_currency, rate=rate, as_of=as_of_str)


def currency_mismatch_warning(
    financial_currency: Optional[str],
    quote_currency: Optional[str],
    *,
    figures_description: str = "figures",
) -> str:
    """Build the currency-mismatch warning block, or "" if there's no mismatch.

    Always includes the raw currency codes; includes a live exchange rate
    when it could be fetched, and an explicit "rate unavailable" note
    (never a guessed number) when it couldn't.

    ``figures_description`` lets callers describe what's below the warning
    (e.g. "raw financial statement values" for a CSV statement dump, or
    "figures" for a summary line list) so the final instruction line reads
    naturally for either shape of output.
    """
    financial_currency = (financial_currency or "").upper().strip()
    quote_currency = (quote_currency or "").upper().strip()
    if not financial_currency or not quote_currency or financial_currency == quote_currency:
        return ""

    lines = [
        f"# Financial statement currency: {financial_currency}",
        f"# Quote/price currency: {quote_currency}",
    ]

    fx = fetch_fx_rate(financial_currency, quote_currency)
    if fx:
        lines.append(
            f"# Live exchange rate: 1 {fx.from_currency} = {fx.rate:.6g} {fx.to_currency} "
            f"(as of {fx.as_of})"
        )
        lines.append(
            f"# The {figures_description} below are in {financial_currency} and not "
            f"converted to {quote_currency} — multiply by the exchange rate above "
            f"before comparing them against {quote_currency}-denominated price, "
            f"market cap, or other quote-currency figures."
        )
    else:
        lines.append(
            f"# Live {financial_currency}->{quote_currency} exchange rate could not be "
            f"fetched right now. The {figures_description} below are in "
            f"{financial_currency} and not converted to {quote_currency} — do not assume "
            f"a 1:1 rate or invent a conversion; flag the currency mismatch instead of "
            f"computing {quote_currency}-denominated ratios from these values."
        )

    return "\n".join(lines)
