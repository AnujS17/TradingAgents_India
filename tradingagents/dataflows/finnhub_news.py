"""Finnhub-backed news data fetching functions."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import requests

from .config import get_config
from .snapshot_cache import snapshot_cached

API_BASE_URL = "https://finnhub.io/api/v1"


def get_api_key() -> str:
    """Retrieve the Finnhub API key from environment variables."""
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise ValueError("FINNHUB_API_KEY environment variable is not set.")
    return api_key


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Retrieve company news for a ticker using Finnhub's company-news API."""
    articles = _cached_api_request(
        "/company-news",
        (("symbol", ticker), ("from", start_date), ("to", end_date)),
    )
    if not articles:
        return f"No Finnhub news found for {ticker} between {start_date} and {end_date}"

    limit = get_config().get("news_article_limit", 30)
    return _format_articles(
        articles[:limit],
        f"{ticker.upper()} News from Finnhub, from {start_date} to {end_date}",
    )


def get_global_news(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve broad market news using Finnhub's market-news API."""
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    articles = _cached_api_request("/news", (("category", "general"), ("minId", 0)))
    filtered = [
        article
        for article in articles
        if _article_in_range(article, start_dt, curr_dt)
    ]
    if not filtered:
        return f"No Finnhub global news found for {curr_date}"

    return _format_articles(
        filtered[:limit],
        f"Global Market News from Finnhub, from {start_dt:%Y-%m-%d} to {curr_date}",
    )


def _make_api_request(path: str, params: dict) -> list[dict]:
    api_params = params.copy()
    api_params["token"] = get_api_key()
    response = requests.get(f"{API_BASE_URL}{path}", params=api_params, timeout=15)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        raise ValueError(data["error"])
    if not isinstance(data, list):
        raise ValueError(f"Unexpected Finnhub response: {data}")
    return data


@lru_cache(maxsize=64)
@snapshot_cached("finnhub_news")
def _cached_api_request(path: str, params_items: tuple) -> list[dict]:
    """params_items is a tuple, not a dict -- lru_cache needs hashable args.
    Raises exactly like _make_api_request; a failure is never cached."""
    return _make_api_request(path, dict(params_items))


def _article_in_range(article: dict, start_dt: datetime, end_dt: datetime) -> bool:
    published = _published_datetime(article)
    if published is None:
        return True
    return start_dt <= published.replace(tzinfo=None) <= end_dt + timedelta(days=1)


def _published_datetime(article: dict) -> Optional[datetime]:
    timestamp = article.get("datetime")
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp))
    except (TypeError, ValueError, OSError):
        return None


def _format_articles(articles: list[dict], heading: str) -> str:
    lines = [f"## {heading}"]
    for article in articles:
        title = article.get("headline") or article.get("title") or "No title"
        source = article.get("source") or "Finnhub"
        published = _published_datetime(article)
        date_part = published.strftime("%Y-%m-%d") if published else "date unknown"
        lines.append(f"### {title} (source: {source}, {date_part})")
        summary = article.get("summary") or ""
        if summary:
            lines.append(summary[:500])
        link = article.get("url") or ""
        if link:
            lines.append(f"Link: {link}")
        lines.append("")
    return "\n".join(lines).strip()
