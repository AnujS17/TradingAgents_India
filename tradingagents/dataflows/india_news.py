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


def fetch_global_india_news(limit: Optional[int] = None) -> str:
    """Fetch broad India-market news for market-context prompts."""
    config = get_config()
    if limit is None:
        limit = config.get("global_india_news_article_limit", 10)
    articles = _fetch_articles(config.get("india_news_feeds", []))
    return _format_articles(
        articles[:limit],
        "Supplemental Global India News",
        empty="<no supplemental global India-news RSS articles found>",
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
    lowered_terms = [term.lower() for term in terms if term]
    matches = []
    for article in articles:
        haystack = f"{article.get('title', '')} {article.get('summary', '')}".lower()
        if any(term in haystack for term in lowered_terms):
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
