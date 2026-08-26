"""GDELT DOC 2.0 news data fetching functions."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from .company_names import news_query_terms
from .config import get_config

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# GDELT throttles aggressively and without warning — bursts of even a few
# requests draw HTTP 429. Because GDELT is first in the news vendor chain,
# an unretried throttle meant the highest-reach source was skipped silently
# and the run fell back to yfinance's ~12-article cap with nothing in the
# report to say it had happened. 503 is included as GDELT returns it when
# the backend is briefly overloaded, which is equally transient.
_RETRYABLE_STATUS = frozenset({429, 503})

# GDELT signals throttling TWO different ways, and handling only the first is
# why the original retry was ineffective: an HTTP 429, *or* an HTTP 200 whose
# body is the plain-text notice below instead of JSON. The 200 form sailed
# past a status-code-only check straight into response.json(), raising
# JSONDecodeError — which route_to_vendor swallows into a silent vendor
# fallback, so a throttled GDELT looked like a GDELT with no articles.
_THROTTLE_BODY_MARKERS = ("please limit requests", "rate limit")

# GDELT's own documented ceiling is "one request every 5 seconds". Spacing our
# own calls is preventive: a run issues get_news + get_global_news (and merging
# means GDELT is hit on every news fetch), which without spacing is a burst
# that earns a sustained block rather than a single 429. Note this cannot lift
# a block already in force — measured 2026-08-10, once GDELT has blocked the
# caller even 6s spacing keeps returning 429 — it only stops us earning one.
_request_lock = threading.Lock()
_last_request_at = 0.0


def _throttled_get(params: dict, timeout: float, min_interval: float):
    """GET the DOC API, never issuing calls closer together than ``min_interval``.

    The wait happens under the lock so concurrent analysts queue on the
    interval; the request itself is issued outside it so a slow response does
    not serialise unrelated callers.
    """
    global _last_request_at

    if min_interval > 0:
        with _request_lock:
            wait = min_interval - (time.monotonic() - _last_request_at)
            if wait > 0:
                time.sleep(wait)
            _last_request_at = time.monotonic()

    return requests.get(API_BASE_URL, params=params, timeout=timeout)


def _is_throttle_response(response) -> bool:
    """True when GDELT is refusing service, by status code or plain-text body."""
    if response.status_code in _RETRYABLE_STATUS:
        return True

    body = (getattr(response, "text", "") or "").strip()
    if not body:
        # GDELT intermittently answers 200 with an empty body. Parsing that
        # raises JSONDecodeError, which reads like a parser bug rather than
        # the transient server hiccup it is, so treat it as retryable.
        # NOTE: this check must precede the JSON test below — `"" in "{["` is
        # True in Python, so an empty body would otherwise be classified as a
        # valid JSON payload and fall straight through to .json().
        return True
    if body.startswith(("{", "[")):
        return False  # real JSON payload, not a notice

    return any(marker in body[:400].lower() for marker in _THROTTLE_BODY_MARKERS)


def _build_ticker_query(ticker: str) -> str:
    """Build the GDELT DOC query for a company.

    Two separate requirements are encoded here:

    * GDELT rejects OR'd terms unless the whole expression is wrapped in
      parentheses ("Queries containing OR'd terms must be surrounded by
      ()."), returning that message as a plain-text 200 — so every
      unwrapped query silently failed.
    * The query must contain strings that actually occur in news prose.
      This previously sent ``("LAURUSLABS.BO" OR "LAURUSLABS.BO")`` — the
      two halves are identical whenever the ticker is already uppercase,
      and no article ever contains the exchange-suffixed symbol. Confirmed
      live: that query returns 0 articles. Since GDELT is *first* in the
      news vendor chain, the highest-reach source was returning nothing for
      every Indian ticker and silently falling through to yfinance.
    """
    terms = news_query_terms(ticker) or (ticker.upper(),)
    return "(" + " OR ".join(f'"{term}"' for term in terms) + ")"


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Retrieve ticker-related web news through GDELT's no-key DOC API."""
    limit = get_config().get("news_article_limit", 30)
    articles = _search_articles(
        query=_build_ticker_query(ticker),
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    if not articles:
        return f"No GDELT news found for {ticker} between {start_date} and {end_date}"
    return _format_articles(
        articles,
        f"{ticker.upper()} Web News from GDELT, from {start_date} to {end_date}",
    )


def get_global_news(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve global market news through GDELT's no-key DOC API."""
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    query = " OR ".join(f'"{term}"' for term in config.get("global_news_queries", []))
    if not query:
        query = '"financial markets" OR "global economy"'
    # Same GDELT OR-must-be-parenthesized requirement as get_news() above.
    query = f"({query})"

    articles = _search_articles(
        query=query,
        start_date=start_dt.strftime("%Y-%m-%d"),
        end_date=curr_date,
        limit=limit,
    )
    if not articles:
        return f"No GDELT global news found for {curr_date}"
    return _format_articles(
        articles,
        f"Global Market News from GDELT, from {start_dt:%Y-%m-%d} to {curr_date}",
    )


def _retry_delay(response: requests.Response, base_delay: float, attempt: int) -> float:
    """Seconds to wait before retrying, honouring Retry-After when sane.

    GDELT usually omits Retry-After, so exponential backoff is the norm; when
    the header is present and parseable as seconds it is authoritative, but
    it is capped so a pathological value can't stall the whole run.
    """
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), 30.0)
        except (TypeError, ValueError):
            pass
    return base_delay * (2 ** attempt)


def _search_articles(query: str, start_date: str, end_date: str, limit: int) -> list[dict]:
    config = get_config()
    max_retries = int(config.get("gdelt_max_retries", 2))
    base_delay = float(config.get("gdelt_retry_base_delay", 5.0))
    timeout = float(config.get("gdelt_timeout_seconds", 15))
    min_interval = float(config.get("gdelt_min_request_interval", 5.0))

    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "sort": "datedesc",
        "maxrecords": min(max(limit, 1), 250),
        "startdatetime": _gdelt_datetime(start_date),
        "enddatetime": _gdelt_datetime(end_date, end_of_day=True),
    }

    response = None
    for attempt in range(max_retries + 1):
        response = _throttled_get(params, timeout, min_interval)
        if not _is_throttle_response(response):
            break
        if attempt == max_retries:
            logger.warning(
                "GDELT throttled (HTTP %s) after %s retries; giving up on query %s",
                response.status_code,
                max_retries,
                query,
            )
            # Raise explicitly rather than relying on raise_for_status: the
            # HTTP 200 plain-text throttle form has no error status to raise
            # from, and would otherwise fall through to response.json() and
            # surface as a confusing JSONDecodeError. HTTPError is a
            # RequestException, so route_to_vendor still falls back cleanly.
            raise requests.exceptions.HTTPError(
                f"GDELT throttled (HTTP {response.status_code}) after "
                f"{max_retries} retries for query {query}"
            )
        delay = _retry_delay(response, base_delay, attempt)
        logger.warning(
            "GDELT rate limited (HTTP %s), retrying in %.0fs (attempt %s/%s)",
            response.status_code,
            delay,
            attempt + 1,
            max_retries,
        )
        time.sleep(delay)

    response.raise_for_status()
    data = response.json()
    articles = data.get("articles", [])
    if not isinstance(articles, list):
        raise ValueError(f"Unexpected GDELT response: {data}")
    return articles[:limit]


def _gdelt_datetime(date_value: str, *, end_of_day: bool = False) -> str:
    dt = datetime.strptime(date_value, "%Y-%m-%d")
    if end_of_day:
        return dt.strftime("%Y%m%d235959")
    return dt.strftime("%Y%m%d000000")


def _format_articles(articles: list[dict], heading: str) -> str:
    lines = [f"## {heading}"]
    for article in articles:
        title = article.get("title") or "No title"
        source = article.get("domain") or article.get("sourcecountry") or "GDELT"
        date_part = _display_date(article.get("seendate"))
        lines.append(f"### {title} (source: {source}, {date_part})")
        language = article.get("language")
        if language:
            lines.append(f"Language: {language}")
        link = article.get("url") or ""
        if link:
            lines.append(f"Link: {link}")
        lines.append("")
    return "\n".join(lines).strip()


def _display_date(value: Optional[str]) -> str:
    if not value:
        return "date unknown"
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return str(value)[:10]
