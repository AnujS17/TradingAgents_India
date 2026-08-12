"""Google News RSS search — per-company news, date-ranged, no API key.

This is the answer to the coverage problem the earlier vendors could not
solve. Every other company-news path in this codebase is either a *feed*
(Yahoo's per-symbol list, hard-capped around 12 articles; the India RSS pool,
which only carries the last 24-48h because "latest news" feeds hold nothing
older) or an API that throttles us out (GDELT). Google News RSS is a genuine
*search* endpoint: an arbitrary query, an explicit date range, the India
edition, and no key.

Measured against the two runs that reported "no company news" (2026-08-11):

    "Laurus Labs"                       -> 71 articles
    "Tata Motors Passenger Vehicles"    -> 100 articles

versus the single competitor story (about Mahindra) that Yahoo returned for
TMPV.NS. It aggregates Business Standard, Moneycontrol, Mint, NDTV, ET and
the rest of the Indian financial press — the same outlets the India RSS pool
only sees for a day.

Note the codebase already had this endpoint wired in ``india_news_feeds``, but
pointed at a generic ``india stock market when:1d`` query for market-wide
context. The mechanism was present; it was simply never aimed at the company.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache

from tradingagents.dataflows.snapshot_cache import snapshot_cached
from typing import Optional
from urllib.parse import quote_plus

import requests

from .company_names import news_search_terms
from .config import get_config
from .rss import (
    BROWSER_HEADERS,
    dedupe_articles,
    format_articles,
    parse_feed,
    sort_articles,
)

logger = logging.getLogger(__name__)

# India edition: hl/gl/ceid together select Indian English coverage rather
# than the US default, which is what surfaces Moneycontrol/Business Standard
# instead of wire syndication.
_SEARCH_URL = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

_SOURCE_NAME = "Google News India"


def _build_query(ticker: str, start_date: str, end_date: str) -> str:
    """Build the Google News search query for a company and date window.

    ``after:``/``before:`` are used rather than the relative ``when:30d`` form
    because they map exactly onto the vendor interface's explicit start/end
    dates, so the caller's window is honoured instead of approximated.
    """
    terms = news_search_terms(ticker) or (ticker.upper(),)
    quoted = " OR ".join(f'"{term}"' for term in terms)
    return f"({quoted}) after:{start_date} before:{end_date}"


def _within_window(published: Optional[datetime], start: datetime, end: datetime) -> bool:
    """Keep undated articles; Google's own filter already bounded the query."""
    if published is None:
        return True
    naive = published.replace(tzinfo=None)
    return start <= naive <= end


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Retrieve company news for ``ticker`` via Google News RSS search."""
    limit = get_config().get("news_article_limit", 30)
    timeout = float(get_config().get("google_news_timeout_seconds", 15))

    try:
        articles = _search_cached(_build_query(ticker, start_date, end_date), timeout)
    except Exception as exc:  # noqa: BLE001 — vendor errors must fall back, not crash
        logger.warning("Google News fetch failed for %s: %s", ticker, exc)
        return f"Error fetching Google News for {ticker}: {exc}"

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    windowed = [a for a in articles if _within_window(a.get("published"), start_dt, end_dt)]

    return format_articles(
        windowed[:limit],
        f"{ticker.upper()} News from Google News, from {start_date} to {end_date}",
        empty=f"No Google News found for {ticker} between {start_date} and {end_date}",
    )


@lru_cache(maxsize=64)
@snapshot_cached("google_news")
def _search_cached(query: str, timeout: float) -> tuple[dict, ...]:
    """Fetch and parse one Google News search, cached per query for the run."""
    url = _SEARCH_URL.format(query=quote_plus(query))
    response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    response.raise_for_status()

    articles = [a for a in parse_feed(response.text, _SOURCE_NAME) if _is_latin_script(a.get("title", ""))]
    for article in articles:
        _attribute_publisher(article)
        _drop_redundant_summary(article)
    # Google returns items in relevance order, not date order.
    return tuple(dedupe_articles(sort_articles(articles)))


def _attribute_publisher(article: dict) -> None:
    """Move the real publisher out of the title and into the source field.

    Google News titles are formatted "Headline - Publisher", so without this
    every article is attributed to "Google News India" and the actual outlet
    (which is what tells an analyst whether to trust the item) is buried in
    the headline text.
    """
    title = article.get("title") or ""
    if " - " not in title:
        return
    headline, _, publisher = title.rpartition(" - ")
    if headline.strip() and publisher.strip():
        article["title"] = headline.strip()
        article["source"] = f"{publisher.strip()} via Google News"


def _drop_redundant_summary(article: dict) -> None:
    """Blank the summary when it merely restates the headline.

    Google News RSS descriptions are the headline with the publisher appended,
    not a real abstract. Left in place that duplicates every headline in the
    prompt — pure token cost across ~30 articles, and it pads the block so it
    reads as more substantive than it is.
    """
    summary = (article.get("summary") or "").strip()
    title = (article.get("title") or "").strip()
    if not summary or not title:
        return
    if _squash(summary).startswith(_squash(title)):
        article["summary"] = ""


def _squash(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _is_latin_script(title: str, threshold: float = 0.5) -> bool:
    """True when the headline is predominantly Latin script.

    The India edition returns some regional-language coverage (Tamil, Hindi,
    Telugu…). Those headlines are unusable by an English-reasoning pipeline
    and just consume prompt budget. The test is proportional rather than
    "contains non-ASCII" on purpose: legitimate English headlines routinely
    carry ₹, en-dashes and smart quotes, and must not be discarded.
    """
    letters = [ch for ch in title if ch.isalpha()]
    if not letters:
        return True
    latin = sum(1 for ch in letters if ch.isascii())
    return (latin / len(letters)) >= threshold


def clear_cache() -> None:
    """Drop the per-query cache (used by tests)."""
    _search_cached.cache_clear()
