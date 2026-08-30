import json

from .alpha_vantage_common import _cached_api_request, format_datetime_for_api
from .config import get_config

# NEWS_SENTIMENT's own "time_published" shape: "20260824T204521". Every
# other vendor's formatter emits a plain "%Y-%m-%d" date in the "(source:
# ..., date)" heading (rss.py/finnhub_news.py/gdelt_news.py/india_news.py
# all match this, and api/news_sources.py's citation parser expects it) --
# converted here rather than passed through so this vendor's output isn't
# the only one with a different date shape.
def _parse_time_published(value: str) -> str | None:
    try:
        from datetime import datetime

        return datetime.strptime(value[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _format_articles(articles: list[dict], heading: str, empty: str) -> str:
    """Same "### {title} (source: {source}, {date})" shape every other
    vendor emits (rss.py::format_articles, finnhub_news.py, gdelt_news.py,
    india_news.py) -- NEWS_SENTIMENT's raw JSON used to be returned
    verbatim instead, which put an unparsed, token-heavy JSON blob into the
    prompt (sentiment scores, topic-relevance breakdowns, per-ticker
    sentiment -- none of it useful to the analyst) and made this vendor's
    output the one api/news_sources.py's citation parser could never read
    (documented there as accepted degradation while this vendor was rarely
    reached; not acceptable now that it is the primary get_global_news
    vendor).
    """
    if not articles:
        return empty

    lines = [f"## {heading}"]
    for article in articles:
        title = (article.get("title") or "").strip() or "No title"
        source = (article.get("source") or "Alpha Vantage").strip()
        date = _parse_time_published(article.get("time_published") or "")
        date_part = date or "date unknown"
        lines.append(f"### {title} (source: {source}, {date_part})")
        summary = (article.get("summary") or "").strip()
        if summary:
            lines.append(summary[:500])
        url = article.get("url") or ""
        if url:
            lines.append(f"Link: {url}")
        lines.append("")
    return "\n".join(lines).strip()


def _parse_feed(raw: str) -> list[dict]:
    """NEWS_SENTIMENT's feed, or [] for anything that isn't the expected
    shape (malformed JSON, a rate-limit/error payload that slipped past
    _make_api_request's own check, or a feed-less response) -- fail open
    to an empty article list rather than raise, matching every other
    vendor's degrade-gracefully behaviour here.
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    feed = data.get("feed")
    return feed if isinstance(feed, list) else []


def get_news(ticker, start_date, end_date) -> str:
    """Returns live and historical market news & sentiment data from premier news outlets worldwide.

    Covers stocks, cryptocurrencies, forex, and topics like fiscal policy, mergers & acquisitions, IPOs.

    Args:
        ticker: Stock symbol for news articles.
        start_date: Start date for news search.
        end_date: End date for news search.

    Returns:
        Formatted string containing news articles (see _format_articles).
    """

    params = (
        ("tickers", ticker),
        ("time_from", format_datetime_for_api(start_date)),
        ("time_to", format_datetime_for_api(end_date)),
    )

    raw = _cached_api_request("NEWS_SENTIMENT", params)
    articles = _parse_feed(raw)
    limit = get_config().get("news_article_limit", 30)
    return _format_articles(
        articles[:limit],
        f"{ticker.upper()} News from Alpha Vantage, from {start_date} to {end_date}",
        empty=f"No Alpha Vantage news found for {ticker} between {start_date} and {end_date}",
    )


def get_global_news(curr_date, look_back_days: int | None = None, limit: int | None = None) -> str:
    """Returns global market news & sentiment data without ticker-specific filtering.

    Covers broad market topics like financial markets, economy, and more.

    Args:
        curr_date: Current date in yyyy-mm-dd format.
        look_back_days: Number of days to look back (default 7).
        limit: Maximum number of articles (default 50).

    Returns:
        Formatted string containing global news articles (see _format_articles).
    """
    from datetime import datetime, timedelta

    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    # Calculate start date
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    params = (
        ("topics", "financial_markets,economy_macro,economy_monetary"),
        ("time_from", format_datetime_for_api(start_date)),
        ("time_to", format_datetime_for_api(curr_date)),
        ("limit", str(limit)),
    )

    raw = _cached_api_request("NEWS_SENTIMENT", params)
    articles = _parse_feed(raw)
    return _format_articles(
        articles[:limit],
        f"Global Market News from Alpha Vantage, from {start_date} to {curr_date}",
        empty=f"No Alpha Vantage global news found for {curr_date}",
    )


def get_insider_transactions(symbol: str) -> dict[str, str] | str:
    """Returns latest and historical insider transactions by key stakeholders.

    Covers transactions by founders, executives, board members, etc.

    Args:
        symbol: Ticker symbol. Example: "IBM".

    Returns:
        Dictionary containing insider transaction data or JSON string.
    """

    return _cached_api_request("INSIDER_TRANSACTIONS", (("symbol", symbol),))
