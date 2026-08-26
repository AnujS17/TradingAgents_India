"""Supplemental India financial-news RSS fetcher.

The core news vendors remain Yahoo Finance and GDELT. This module adds
lightweight, no-key RSS context from Indian business and markets outlets
that often surface promoter-action, regulatory, and sector signals before
they are fully reflected in finance-only feeds.
"""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache

from tradingagents.dataflows.snapshot_cache import snapshot_cached
from typing import Iterable, Optional

import requests

from .company_names import company_search_terms
from .config import get_config

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36 TradingAgents/0.2"
    ),
    "Accept": "application/rss+xml,application/xml,text/xml,*/*",
}

_TAG_RE = re.compile(r"<[^>]+>")

# Substring-matched (case-insensitive, via _filter_articles) against each
# raw RSS headline/summary in fetch_global_india_news. Deliberately broader
# than global_news_queries in default_config.py: that list is a SEARCH
# query, so it must stay short enough for GDELT/Yahoo to actually match a
# phrase; this is a local filter over an already-fetched, already
# India-sourced pool, so there's no cost to casting a wide net. Without
# this, fetch_global_india_news returned the unfiltered top-of-feed dump —
# whatever these outlets happened to be running that hour, which is exactly
# as likely to be a company-specific story about an unrelated company (a
# pharma recall, a telecom licensing dispute) as genuine market/macro
# context, regardless of the ticker being analysed.
_MACRO_TERMS = (
    # Monetary policy
    "RBI", "repo rate", "reverse repo", "monetary policy", "MPC",
    "interest rate", "liquidity",
    # Indices and market structure
    "Nifty", "Sensex", "Bank Nifty", "BSE", "NSE", "SEBI",
    "stock market", "equity market", "market cap", "bull market",
    "bear market", "market rally", "market correction", "volatility",
    "bond yield", "G-Sec", "index fund",
    # Institutional flows
    "FII", "DII", "FPI", "foreign institutional", "domestic institutional",
    "foreign portfolio", "institutional investors",
    # Currency and external sector
    "rupee", "INR", "forex reserves", "current account deficit",
    "trade deficit", "exchange rate",
    # Fiscal and regulatory policy
    "Union Budget", "GST", "fiscal deficit", "disinvestment",
    "PLI scheme", "RBI intervention",
    # Macro indicators
    "inflation", "CPI", "WPI", "GDP", "IIP", "core sector",
    "manufacturing PMI", "services PMI", "industrial production",
    # Primary/fund markets
    "IPO market", "mutual fund", "SIP inflow", "block deal", "bulk deal",
)


def fetch_ticker_india_news(ticker: str, limit: Optional[int] = None) -> str:
    """Fetch supplemental India-market articles relevant to a ticker."""
    config = get_config()
    if limit is None:
        limit = config.get("india_news_article_limit", 8)
    terms = _terms_for_ticker(ticker)
    articles = _fetch_articles(config.get("india_news_feeds", []))
    matches = _filter_articles(articles, terms)
    return _format_articles(
        matches[:limit],
        f"Supplemental India News for {ticker.upper()}",
        empty=f"<no supplemental India-news RSS matches found for {ticker.upper()}>",
    )


def get_global_news(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Vendor-interface wrapper around fetch_global_india_news, registered
    as the "india_rss" vendor for the get_global_news tool (see
    dataflows/interface.py's VENDOR_METHODS and default_config.py's
    tool_vendors.get_global_news).

    Replaces get_global_news_yfinance in the default chain. Diagnosed
    2026-08-25: get_global_news_yfinance is also in merged_news_vendors
    (shared with get_news, where merging google_news+yfinance is genuinely
    useful) -- but for get_global_news specifically, that meant yfinance's
    merge pass always "succeeded" (returned SOME string) and short-circuited
    route_to_vendor before GDELT was ever tried, and yfinance's own
    yf.Search() ignores India-specific query terms and returns generic
    trending Yahoo Finance content regardless (confirmed live: querying
    "RBI repo rate" returned Strait-of-Hormuz crude-oil headlines). This
    fetcher has no such failure mode -- it is the same already-filtered
    (_MACRO_TERMS) India RSS pool used elsewhere, not a search query that
    can silently mismatch.

    curr_date/look_back_days are accepted only for interface-shape
    compatibility with the other vendor get_global_news implementations;
    India RSS feeds carry no historical window to filter by, so they are
    unused here -- the same way fetch_global_india_news's own callers
    already treat it.
    """
    return fetch_global_india_news(limit=limit)


def fetch_global_india_news(limit: Optional[int] = None) -> str:
    """Fetch India macro/market-context news for market-context prompts.

    Filtered to genuine market/macro coverage (_MACRO_TERMS) rather than
    the raw top-of-feed dump: this block is meant to be the day's
    market-wide backdrop, not a second, unfiltered pass at company-specific
    stories that just happened to be trending on these feeds when fetched.
    """
    config = get_config()
    if limit is None:
        limit = config.get("global_india_news_article_limit", 10)
    articles = _fetch_articles(config.get("india_news_feeds", []))
    matches = _filter_articles(articles, _MACRO_TERMS)
    return _format_articles(
        matches[:limit],
        "Supplemental Global India News",
        empty="<no supplemental global India-news RSS articles matched market/macro terms>",
    )


def _terms_for_ticker(ticker: str) -> tuple[str, ...]:
    """Terms to match this ticker against RSS headlines and summaries.

    Delegates to the shared resolver so matching works for any listed symbol.
    This used to consult a hardcoded 20-ticker keyword map and fall back to
    ticker-only matching for everything else — which meant every stock outside
    those 20 large caps was matched as e.g. "LAURUSLABS", a string Indian
    financial media never prints (they write "Laurus Labs"), so mid-caps with
    real coverage were reported as having no news at all.
    """
    return company_search_terms(ticker)


def _fetch_articles(feeds: Iterable[dict]) -> list[dict]:
    """Fetch and cache raw articles for this exact set of feeds.

    Ticker-specific filtering happens on top of this (uncached, since
    different tickers need different filtered slices of the same raw pool)
    — only the network fetch + parse is cached. Without this, every
    fetch_ticker_india_news() call re-fetches all configured RSS feeds from
    scratch, unlike every sibling fetcher (stocktwits.py, reddit.py,
    india_insider.py), which is wasteful and raises re-block risk on
    feeds that are already known to be bot-sensitive.
    """
    feeds_key = tuple((feed.get("name", "Unknown"), feed.get("url", "")) for feed in feeds)
    return list(_fetch_articles_cached(feeds_key))


@lru_cache(maxsize=8)
@snapshot_cached("india_news")
def _fetch_articles_cached(feeds_key: tuple[tuple[str, str], ...]) -> list[dict]:
    articles: list[dict] = []
    for name, url in feeds_key:
        if not url:
            continue
        try:
            response = requests.get(url, headers=_BROWSER_HEADERS, timeout=8)
            response.raise_for_status()
            articles.extend(_parse_feed(response.text, name))
        except Exception as exc:
            logger.warning("India-news RSS fetch failed for %s: %s", name, exc)
    return _dedupe_articles(_sort_articles(articles))


def _parse_feed(xml_text: str, source: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    if root.tag.endswith("rss"):
        items = root.findall(".//item")
        return [_article_from_rss_item(item, source) for item in items]

    entries = [
        element
        for element in root.iter()
        if _local_name(element.tag) == "entry"
    ]
    return [_article_from_atom_entry(entry, source) for entry in entries]


def _article_from_rss_item(item: ET.Element, source: str) -> dict:
    return {
        "title": _text(item, "title") or "No title",
        "summary": _clean_summary(_text(item, "description") or _text(item, "summary")),
        "link": _text(item, "link"),
        "published": _parse_date(_text(item, "pubDate") or _text(item, "published")),
        "source": source,
    }


def _article_from_atom_entry(entry: ET.Element, source: str) -> dict:
    link = ""
    for child in entry:
        if _local_name(child.tag) == "link":
            link = child.attrib.get("href", "")
            if link:
                break
    return {
        "title": _text(entry, "title") or "No title",
        "summary": _clean_summary(_text(entry, "summary") or _text(entry, "content")),
        "link": link,
        "published": _parse_date(_text(entry, "updated") or _text(entry, "published")),
        "source": source,
    }


def _text(parent: ET.Element, child_name: str) -> str:
    for child in parent:
        if _local_name(child.tag) == child_name:
            return (child.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def _clean_summary(value: str) -> str:
    cleaned = html.unescape(_TAG_RE.sub("", value or "")).replace("\n", " ").strip()
    return re.sub(r"\s+", " ", cleaned)


def _filter_articles(articles: Iterable[dict], terms: Iterable[str]) -> list[dict]:
    """Word-boundary match, not plain substring containment.

    Found live 2026-08-25: _MACRO_TERMS' "NSE" matched inside "immense" (a
    CSR/PR story about Adani, nothing to do with the exchange), because a
    3-letter acronym is a substring of plenty of ordinary English words
    ("immense", "intense", "expense", "license", "response" all contain
    "nse"). company_search_terms already avoids this class of bug for
    longer name-derived terms via _MIN_TERM_LENGTH, but the acronyms in
    _MACRO_TERMS (RBI, NSE, BSE, FII, DII, FPI, CPI, WPI, GDP, IIP, GST,
    MPC -- all 3 characters) are too short for a length floor to help;
    they need an actual word boundary instead of a substring check.
    """
    patterns = [
        re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        for term in terms
        if term
    ]
    matches = []
    for article in articles:
        haystack = f"{article.get('title', '')} {article.get('summary', '')}"
        if any(pattern.search(haystack) for pattern in patterns):
            matches.append(article)
    return matches


def _sort_articles(articles: Iterable[dict]) -> list[dict]:
    def sort_key(item: dict) -> float:
        published = item.get("published")
        if published is None:
            return 0.0
        return published.timestamp()

    return sorted(
        articles,
        key=sort_key,
        reverse=True,
    )


def _dedupe_articles(articles: Iterable[dict]) -> list[dict]:
    seen = set()
    unique = []
    for article in articles:
        key = (article.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(article)
    return unique


def _format_articles(articles: list[dict], heading: str, *, empty: str) -> str:
    if not articles:
        return empty

    lines = [f"## {heading}"]
    for article in articles:
        title = article.get("title", "No title")
        source = article.get("source", "Unknown")
        published = article.get("published")
        date_part = published.strftime("%Y-%m-%d") if published else "date unknown"
        lines.append(f"### {title} (source: {source}, {date_part})")
        summary = article.get("summary", "")
        if summary:
            lines.append(summary[:500])
        link = article.get("link", "")
        if link:
            lines.append(f"Link: {link}")
        lines.append("")
    return "\n".join(lines).strip()
