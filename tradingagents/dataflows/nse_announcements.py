"""NSE corporate announcements — official exchange filings, no API key.

Every other source in this pipeline is journalism or social chatter: someone's
report of an event. This is the event itself, filed by the company with the
exchange — board meetings, results dates, dividends, and announcement
subjects, straight from NSE's ``top-corp-info`` endpoint.

The concrete gap it closes: in the TMPV.NS run of 2026-08-10 the only hint of
an upcoming earnings catalyst came from a Reddit user mentioning "results on
12th August", which the analysts then reasoned over. NSE's own board-meeting
filing says the meeting is on **13-Aug-2026**, to approve audited results. The
run was working from a retail comment that was a day wrong, because the
authoritative source was never consulted.

NSE requires a browser-shaped session with cookies primed from the homepage
before its JSON API responds; a bare request is rejected. Every failure
degrades to a placeholder string so a blocked NSE never blocks a run.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import requests

from .company_names import base_symbol
from .config import get_config

logger = logging.getLogger(__name__)

_HOME_URL = "https://www.nseindia.com"
_API_URL = "https://www.nseindia.com/api/top-corp-info?symbol={symbol}&market=equities"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# Sections rendered, in the order an analyst cares about them: what is coming
# (board meetings), what was just filed (announcements), then cash events.
_SECTIONS = (
    ("borad_meeting", "Upcoming / Recent Board Meetings", ("meetingdate", "purpose")),
    ("latest_announcements", "Latest Exchange Announcements", ("broadcastdate", "subject")),
    ("corporate_actions", "Corporate Actions", ("exdate", "purpose")),
)


def fetch_corporate_announcements(ticker: str, curr_date: str, limit: Optional[int] = None) -> str:
    """Fetch NSE corporate filings for ``ticker``, formatted for prompt injection.

    ``curr_date`` participates in the cache key so a re-run on a different
    trade date refetches rather than replaying yesterday's filings.
    """
    if limit is None:
        limit = get_config().get("nse_announcement_limit", 6)
    timeout = float(get_config().get("nse_timeout_seconds", 15))
    return _fetch_cached(base_symbol(ticker), curr_date, int(limit), timeout)


@lru_cache(maxsize=64)
def _fetch_cached(symbol: str, curr_date: str, limit: int, timeout: float) -> str:
    if not symbol:
        return "<no NSE symbol resolved for corporate announcements>"

    try:
        payload = _request_corp_info(symbol, timeout)
    except Exception as exc:  # noqa: BLE001 — never block a run on NSE being down
        logger.warning("NSE corporate-info fetch failed for %s: %s", symbol, exc)
        return f"<NSE corporate announcements unavailable for {symbol}: {type(exc).__name__}>"

    if not isinstance(payload, dict):
        return f"<NSE corporate announcements unavailable for {symbol}: unexpected response>"

    blocks = []
    for key, heading, fields in _SECTIONS:
        rows = _rows(payload, key)
        if not rows:
            continue
        lines = [f"### {heading}"]
        for row in rows[:limit]:
            rendered = " — ".join(
                str(row.get(field)).strip()
                for field in fields
                if row.get(field) not in (None, "")
            )
            if rendered:
                lines.append(f"- {rendered}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    if not blocks:
        return f"<no NSE corporate announcements found for {symbol}>"

    return (
        f"## NSE Corporate Filings for {symbol}\n"
        "Source: NSE exchange filings (authoritative — prefer these dates over "
        "any date inferred from news or social posts).\n\n" + "\n\n".join(blocks)
    )


def _rows(payload: dict, key: str) -> list[dict]:
    """Return the row list for a section, tolerating NSE's shape drift."""
    section = payload.get(key)
    if isinstance(section, dict):
        data = section.get("data")
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    if isinstance(section, list):
        return [r for r in section if isinstance(r, dict)]
    return []


def _request_corp_info(symbol: str, timeout: float) -> dict:
    """Prime cookies on the NSE homepage, then call the JSON API.

    NSE rejects API calls that arrive without a session cookie set by a prior
    homepage visit, so the two requests must share a Session.
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.get(_HOME_URL, timeout=timeout)
    response = session.get(_API_URL.format(symbol=symbol), timeout=timeout)
    response.raise_for_status()
    return response.json()


def clear_cache() -> None:
    """Drop the per-symbol cache (used by tests)."""
    _fetch_cached.cache_clear()
