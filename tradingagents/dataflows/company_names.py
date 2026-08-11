"""Company-name search terms for text-matching data sources.

Several fetchers (india_news RSS, Reddit) find articles/posts by substring
matching a ticker against free text. Matching on the ticker alone silently
fails for most of the market: an RSS headline says "Laurus Labs", never
"LAURUSLABS", so a mid-cap with real coverage looks like a company nobody
wrote about (observed live: the LAURUSLABS.BO run on 2026-08-10 reported
"no supplemental India-news RSS matches" while Business Line and
Moneycontrol were actively carrying the name).

The previous approach hardcoded a 20-ticker keyword map, so exactly those
20 large caps matched by name and every other ticker on NSE/BSE fell back
to ticker-only matching. This module resolves the real company name from
yfinance instead, so name matching works for any listed symbol, and keeps
a curated alias table only for colloquial names that no data source
returns (RIL, HUL, L&T).

This lives in ``dataflows`` rather than reusing
``agent_utils.resolve_instrument_identity`` because ``agent_utils`` imports
from ``dataflows`` — the reverse dependency would be circular.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import yfinance as yf

logger = logging.getLogger(__name__)

_INDIA_SUFFIXES = (".NS", ".BO")

# Trailing corporate-form tokens stripped to get the name people actually
# write. "Laurus Labs Limited" -> "Laurus Labs".
_CORPORATE_SUFFIX_TOKENS = {
    "limited", "ltd", "ltd.", "inc", "inc.", "incorporated",
    "corporation", "corp", "corp.", "plc", "company", "co", "co.",
    "sa", "nv", "ag", "holdings", "holding",
}

# Shortest a name-derived term may be before it is dropped. Two- and
# three-character fragments ("ITC", "3M") match far too much unrelated
# prose to be usable as a substring filter; the bare ticker already covers
# those cases exactly.
_MIN_TERM_LENGTH = 4

# Colloquial names that no API returns but Indian financial media use
# constantly. Supplements the resolved name; never replaces it.
_CURATED_ALIASES = {
    "RELIANCE": ("RIL", "Jio", "Reliance Retail"),
    "HINDUNILVR": ("HUL",),
    "SBIN": ("SBI",),
    "LT": ("L&T",),
    "BHARTIARTL": ("Airtel",),
    "TCS": ("TCS",),
    "INFY": ("Infosys",),
    "HCLTECH": ("HCLTech",),
    "MARUTI": ("Maruti Suzuki",),
    "SUNPHARMA": ("Sun Pharma",),
    "KOTAKBANK": ("Kotak Bank",),
    "ADANIENT": ("Adani",),
}


def base_symbol(ticker: str) -> str:
    """Strip an NSE/BSE exchange suffix from ``ticker``."""
    normalized = (ticker or "").upper().strip()
    for suffix in _INDIA_SUFFIXES:
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def _strip_corporate_suffix(name: str) -> str:
    """Drop trailing corporate-form words: 'Laurus Labs Limited' -> 'Laurus Labs'."""
    tokens = re.split(r"\s+", name.strip())
    while tokens and tokens[-1].lower().strip(".,") in _CORPORATE_SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


@lru_cache(maxsize=256)
def resolve_company_name(ticker: str) -> str:
    """Return the company's display name for ``ticker``, or "" if unresolvable.

    Best-effort: any network/lookup failure returns "" so callers degrade to
    ticker-only matching rather than failing the run.
    """
    try:
        info = yf.Ticker(ticker.upper().strip()).info or {}
    except Exception as exc:  # noqa: BLE001 — fail open, never block the run
        logger.debug("Company-name resolution failed for %s: %s", ticker, exc)
        return ""

    for key in ("longName", "shortName"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = value.strip()
            if cleaned.lower() not in {"none", "n/a", "nan", "null"}:
                # shortName is often ALL CAPS ("LAURUS LABS LIMITED"); title-case
                # it so it reads naturally. Matching is case-insensitive anyway.
                return cleaned if not cleaned.isupper() else cleaned.title()
    return ""


def clear_caches() -> None:
    """Drop memoised name lookups.

    Public because the resolution is cached at module level and both tests
    and long-lived processes need a supported way to invalidate it, rather
    than reaching into whichever private function currently holds the cache.
    """
    # getattr-guarded: tests monkeypatch ``resolve_company_name`` with a plain
    # lambda, which has no ``cache_clear``. Clearing must stay safe in that
    # state, since the whole point of calling it there is to drop values
    # memoised before the patch was applied.
    for fn in (resolve_company_name, _resolved_parts):
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()


def _dedupe(terms: list[str]) -> tuple[str, ...]:
    """Dedupe case-insensitively, preserving first-seen order."""
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            unique.append(term)
    return tuple(unique)


@lru_cache(maxsize=256)
def _resolved_parts(ticker: str) -> tuple[str, str, str]:
    """Return ``(base_symbol, full_name, short_name)`` for ``ticker``.

    ``short_name`` is the corporate-suffix-stripped form. Either name is ""
    when unresolvable or too short to discriminate.
    """
    base = base_symbol(ticker)
    if not base:
        return ("", "", "")

    name = resolve_company_name(ticker)
    if not name:
        return (base, "", "")

    short = _strip_corporate_suffix(name)
    return (
        base,
        name if len(name) >= _MIN_TERM_LENGTH else "",
        short if len(short) >= _MIN_TERM_LENGTH else "",
    )


def company_search_terms(ticker: str) -> tuple[str, ...]:
    """Build the set of strings worth substring-matching for ``ticker``.

    Always includes the bare ticker and its ``$``-prefixed cashtag form; adds
    the resolved company name and its suffix-stripped variant when they are
    long enough to be discriminating, plus any curated colloquial aliases.
    Terms are returned original-cased; callers lowercase both sides.

    Intended for sources whose text includes social conventions (Reddit,
    India-news RSS). For news-article search use :func:`news_search_terms`.
    """
    base, full_name, short_name = _resolved_parts(ticker)
    if not base:
        return ()

    terms = [base, f"${base}", full_name, short_name]
    terms.extend(_CURATED_ALIASES.get(base, ()))
    return _dedupe([t for t in terms if t])


def news_search_terms(ticker: str) -> tuple[str, ...]:
    """Search terms for news-article queries (GDELT and similar).

    Differs from :func:`company_search_terms` in two ways that matter for a
    keyword news index rather than a social feed:

    * **No ``$`` cashtag.** That is a StockTwits/Reddit convention; it does
      not appear in news prose, so it only pads the query.
    * **No redundant long name.** These are phrase queries, so "Laurus Labs"
      already matches every article containing "Laurus Labs Limited" —
      sending both wastes query budget for zero extra recall.

    The bare ticker is always kept alongside the name: some outlets write
    only the symbol, and for most Indian tickers ("LAURUSLABS") it is
    distinctive enough not to pull in unrelated prose.
    """
    base, full_name, short_name = _resolved_parts(ticker)
    if not base:
        return ()

    terms = [base, short_name or full_name]
    terms.extend(_CURATED_ALIASES.get(base, ()))
    return _dedupe([t for t in terms if t])
