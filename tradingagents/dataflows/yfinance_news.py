"""yfinance-based news data fetching functions."""

from functools import lru_cache
from typing import Optional

import yfinance as yf
from datetime import datetime
from dateutil.relativedelta import relativedelta

from .company_names import news_search_terms
from .config import get_config
from .snapshot_cache import snapshot_cached
from .stockstats_utils import yf_retry


def _company_specificity_note(ticker: str, articles: list[dict]) -> str:
    """Flag how many returned articles actually name the company.

    Yahoo's per-ticker feed includes sector and peer coverage: the only
    "company news" returned for TMPV.NS on 2026-08-10 was a Mahindra & Mahindra
    earnings story, which the news analyst then reasoned over as if it were
    TMPV's own news. Counting rather than per-article labelling is deliberate —
    an article can legitimately refer to the company by a name we did not
    resolve (TMPV is written "Tata Motors" in the press), so tagging individual
    items would produce confident mislabels. A count states the uncertainty
    without asserting anything false about a specific article.
    """
    terms = [t.lower() for t in news_search_terms(ticker)]
    if not terms or not articles:
        return ""

    named = sum(
        1
        for a in articles
        if any(t in f"{a.get('title', '')} {a.get('summary', '')}".lower() for t in terms)
    )
    if named == len(articles):
        return ""

    return (
        f"\n_Coverage note: {named} of {len(articles)} article(s) above explicitly name "
        f"{' / '.join(news_search_terms(ticker))}. The remainder came from this ticker's "
        "vendor feed but may be sector or peer coverage. Do not treat an article as "
        "company-specific news unless it names the company._\n"
    )


def _extract_article_data(article: dict) -> dict:
    """Extract article data from yfinance news format (handles nested 'content' structure)."""
    # Handle nested content structure
    if "content" in article:
        content = article["content"]
        title = content.get("title", "No title")
        summary = content.get("summary", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")

        # Get URL from canonicalUrl or clickThroughUrl
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")

        # Get publish date
        pub_date_str = content.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    else:
        # Fallback for flat structure
        return {
            "title": article.get("title", "No title"),
            "summary": article.get("summary", ""),
            "publisher": article.get("publisher", "Unknown"),
            "link": article.get("link", ""),
            "pub_date": None,
        }


@lru_cache(maxsize=64)
@snapshot_cached("yfinance_news")
def _fetch_news_cached(ticker: str, article_limit: int) -> tuple[dict, ...]:
    """Raw fetch, cached per (ticker, article_limit, snapshot date). The
    vendor call itself takes no date range -- yfinance just returns its
    latest N articles and the caller filters by date afterward -- so date
    isn't part of this key; a different start_date/end_date within the same
    day still replays the same underlying fetch, which is correct."""
    stock = yf.Ticker(ticker)
    news = yf_retry(lambda: stock.get_news(count=article_limit))
    return tuple(news) if news else ()


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Retrieve news for a specific stock ticker using yfinance.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Formatted string containing news articles
    """
    article_limit = get_config()["news_article_limit"]
    try:
        news = _fetch_news_cached(ticker, article_limit)

        if not news:
            return f"No news found for {ticker}"

        # Parse date range for filtering
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        news_str = ""
        kept: list[dict] = []

        for article in news:
            data = _extract_article_data(article)

            # Filter by date if publish time is available
            if data["pub_date"]:
                pub_date_naive = data["pub_date"].replace(tzinfo=None)
                if not (start_dt <= pub_date_naive <= end_dt + relativedelta(days=1)):
                    continue

            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"
            kept.append(data)

        if not kept:
            return f"No news found for {ticker} between {start_date} and {end_date}"

        return (
            f"## {ticker} News, from {start_date} to {end_date}:\n\n"
            f"{news_str}{_company_specificity_note(ticker, kept)}"
        )

    except Exception as e:
        return f"Error fetching news for {ticker}: {str(e)}"


@lru_cache(maxsize=64)
@snapshot_cached("yfinance_global_news")
def _search_global_news_cached(query: str, news_count: int) -> tuple[dict, ...]:
    """Raw per-query fetch, mirroring google_news.py's _search_cached for the
    same reason: the query already encodes everything the search needs, one
    entry per (query, news_count, snapshot date)."""
    search = yf_retry(lambda: yf.Search(query=query, news_count=news_count, enable_fuzzy_query=True))
    return tuple(search.news) if search.news else ()


def get_global_news_yfinance(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """
    Retrieve global/macro economic news using yfinance Search.

    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back. ``None`` falls back to
            ``global_news_lookback_days`` from the active config.
        limit: Maximum number of articles to return. ``None`` falls back to
            ``global_news_article_limit`` from the active config.

    Returns:
        Formatted string containing global news articles
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    search_queries = config["global_news_queries"]

    all_news = []
    seen_titles = set()

    try:
        for query in search_queries:
            news_items = _search_global_news_cached(query, limit)

            for article in news_items:
                # Handle both flat and nested structures
                if "content" in article:
                    data = _extract_article_data(article)
                    title = data["title"]
                else:
                    title = article.get("title", "")

                # Deduplicate by title
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    all_news.append(article)

            if len(all_news) >= limit:
                break

        if not all_news:
            return f"No global news found for {curr_date}"

        # Calculate date range
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - relativedelta(days=look_back_days)
        start_date = start_dt.strftime("%Y-%m-%d")

        news_str = ""
        for article in all_news[:limit]:
            # Handle both flat and nested structures
            if "content" in article:
                data = _extract_article_data(article)
                # Skip articles published after curr_date (look-ahead guard)
                if data.get("pub_date"):
                    pub_naive = data["pub_date"].replace(tzinfo=None) if hasattr(data["pub_date"], "replace") else data["pub_date"]
                    if pub_naive > curr_dt + relativedelta(days=1):
                        continue
                title = data["title"]
                publisher = data["publisher"]
                link = data["link"]
                summary = data["summary"]
            else:
                title = article.get("title", "No title")
                publisher = article.get("publisher", "Unknown")
                link = article.get("link", "")
                summary = ""

            news_str += f"### {title} (source: {publisher})\n"
            if summary:
                news_str += f"{summary}\n"
            if link:
                news_str += f"Link: {link}\n"
            news_str += "\n"

        return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"

    except Exception as e:
        return f"Error fetching global news: {str(e)}"
