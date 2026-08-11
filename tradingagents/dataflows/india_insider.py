"""Promoter / large-holder bulk-deal fetcher for NSE-listed tickers.

India's insider-disclosure regime (SEBI PIT Regulations) isn't exposed by
yfinance the way US Form-4 data is. This module uses NSE's own official
bulk-deals feed (trades >= 0.5% of a company's equity in a single
transaction, on the NSE cash-market segment) as a practical proxy signal —
promoters, large investors, and institutions are frequent participants in
bulk deals, and Indian analysts already treat this feed as a standard
promoter/large-holder activity indicator.

Data-freshness caveat (important, and reflected in the output text): NSE's
simple bulk-deals endpoint only exposes the most recently completed trading
session — there is no historical date-range parameter on this feed. This
function is therefore a "most-recent-activity" signal, not a point-in-time
lookup for ``curr_date``. When ``curr_date`` is more than a few days in the
past (e.g. a backtest run), the output says so explicitly rather than
silently presenting today's data as if it were historical.

Requires the ``jugaad-data`` package (wraps NSE's public, no-key endpoints).
Degrades gracefully — returns a placeholder string — if the package is
missing, the network call fails, or NSE's feed is unreachable/blocked.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from functools import lru_cache
from typing import Optional

from .config import get_config

logger = logging.getLogger(__name__)

_NSE_SUFFIXES = (".NS", ".BO")

# NSE bulk-deals CSV date format, e.g. "07-AUG-2026"
_CSV_DATE_FORMAT = "%d-%b-%Y"

_STALE_DATA_WARNING_DAYS = 3


def _base_symbol(ticker: str) -> str:
    normalized = ticker.upper().strip()
    for suffix in _NSE_SUFFIXES:
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


@lru_cache(maxsize=1)
def _fetch_bulk_deals_csv() -> Optional[str]:
    """Fetch the raw NSE bulk-deals CSV once per process; cached thereafter.

    Cached because the underlying feed only ever exposes one trading
    session's worth of data, so re-fetching mid-run cannot yield anything
    new — and NSE's endpoint is rate-limit-sensitive.
    """
    try:
        from jugaad_data.nse import NSEArchives
    except ImportError:
        logger.warning("jugaad-data is not installed; bulk-deal data unavailable.")
        return None

    try:
        return NSEArchives().bulk_deals_raw()
    except Exception as exc:
        logger.warning("NSE bulk-deals fetch failed: %s", exc)
        return None


def _parse_bulk_deals(csv_text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if row.get("Symbol"):
            rows.append(row)
    return rows


def _row_date(row: dict) -> Optional[datetime]:
    try:
        return datetime.strptime(row.get("Date", ""), _CSV_DATE_FORMAT)
    except ValueError:
        return None


def fetch_promoter_bulk_deals(ticker: str, curr_date: str, limit: Optional[int] = None) -> str:
    """Fetch NSE bulk-deal activity for ``ticker``, formatted for prompt injection.

    Args:
        ticker: Ticker symbol, with or without an ``.NS``/``.BO`` suffix.
        curr_date: The analysis date (``YYYY-MM-DD``) — used only to flag
            when the fetched data is stale relative to the requested date,
            not to filter it (see module docstring on the freshness caveat).
        limit: Maximum number of deal rows to include; omit to use the
            configured default (``promoter_bulk_deals_limit``).
    """
    if limit is None:
        limit = get_config().get("promoter_bulk_deals_limit", 15)
    symbol = _base_symbol(ticker)

    csv_text = _fetch_bulk_deals_csv()
    if csv_text is None:
        return f"<bulk-deal data unavailable for {symbol}: NSE feed unreachable or jugaad-data not installed>"

    try:
        rows = _parse_bulk_deals(csv_text)
    except Exception as exc:
        logger.warning("Failed to parse NSE bulk-deals CSV: %s", exc)
        return f"<bulk-deal data unavailable for {symbol}: could not parse NSE feed>"

    matches = [row for row in rows if row.get("Symbol", "").upper() == symbol]
    if not matches:
        return f"<no bulk-deal activity found for {symbol} in the most recent NSE session>"

    matches = matches[:limit]
    data_date = _row_date(matches[0])
    staleness_note = ""
    if data_date:
        try:
            requested = datetime.strptime(curr_date, "%Y-%m-%d")
            if abs((requested.date() - data_date.date()).days) > _STALE_DATA_WARNING_DAYS:
                staleness_note = (
                    f"\nNote: this is the most recent bulk-deal session NSE exposes "
                    f"({data_date.strftime('%Y-%m-%d')}); NSE's feed has no historical "
                    f"date lookup, so it may not reflect activity as of the requested "
                    f"analysis date {curr_date}.\n"
                )
        except ValueError:
            pass

    lines = [
        f"## NSE Bulk-Deal Activity for {symbol}",
        f"Session: {matches[0].get('Date', 'unknown date')} "
        f"({len(matches)} deal{'s' if len(matches) != 1 else ''} found)",
        staleness_note.strip(),
        "",
    ]
    for row in matches:
        client = row.get("Client Name", "Unknown")
        side = row.get("Buy/Sell", "?")
        qty = row.get("Quantity Traded", "?")
        price = row.get("Trade Price / Wght. Avg. Price", "?")
        lines.append(f"- {side}: {client} — qty {qty} @ avg price {price}")

    lines.append(
        "\nContext: NSE bulk deals capture single trades >=0.5% of a company's "
        "equity on the cash-market segment — a widely used proxy for "
        "promoter/large-investor activity, not an exhaustive insider-trading "
        "disclosure feed."
    )
    return "\n".join(line for line in lines if line)
