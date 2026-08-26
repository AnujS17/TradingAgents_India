from unittest.mock import MagicMock, patch

import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows import india_news
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.india_news import fetch_global_india_news, fetch_ticker_india_news
from tradingagents.dataflows.india_news import get_global_news as india_rss_get_global_news


@pytest.fixture(autouse=True)
def reset_config():
    set_config(default_config.DEFAULT_CONFIG)
    india_news._fetch_articles_cached.cache_clear()
    yield
    set_config(default_config.DEFAULT_CONFIG)
    india_news._fetch_articles_cached.cache_clear()


RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Reliance Industries Q1 results beat estimates on Jio, retail growth</title>
      <description>Reliance posts strong earnings driven by telecom and retail arms.</description>
      <link>https://example.com/reliance-q1</link>
      <pubDate>Mon, 01 Jun 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>RBI holds repo rate steady amid inflation concerns</title>
      <description>Monetary policy committee maintains status quo.</description>
      <link>https://example.com/rbi-repo-rate</link>
      <pubDate>Sun, 31 May 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.mark.unit
def test_fetch_ticker_india_news_filters_by_ticker_keywords():
    set_config(
        {
            **default_config.DEFAULT_CONFIG,
            "india_news_feeds": [{"name": "Example India", "url": "https://example.com/rss"}],
            "india_news_article_limit": 5,
        }
    )
    response = MagicMock()
    response.text = RSS
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.india_news.requests.get", return_value=response):
        result = fetch_ticker_india_news("RELIANCE.NS")

    assert "Supplemental India News for RELIANCE.NS" in result
    assert "Reliance Industries Q1 results" in result
    assert "RBI holds repo rate" not in result


@pytest.mark.unit
def test_fetch_global_india_news_includes_feed_source():
    set_config(
        {
            **default_config.DEFAULT_CONFIG,
            "india_news_feeds": [{"name": "Example India", "url": "https://example.com/rss"}],
            "global_india_news_article_limit": 1,
        }
    )
    response = MagicMock()
    response.text = RSS
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.india_news.requests.get", return_value=response):
        result = fetch_global_india_news()

    assert "Supplemental Global India News" in result
    assert "source: Example India" in result
    assert result.count("### ") == 1


@pytest.mark.unit
def test_fetch_global_india_news_filters_out_company_specific_noise():
    """The actual bug: fetch_global_india_news used to return the raw
    top-of-feed dump with zero relevance filtering, so a company-specific
    story about a totally unrelated company (here, Reliance) was just as
    likely to appear as genuine macro/market context (here, the RBI repo
    rate item). Only the macro item should survive."""
    set_config(
        {
            **default_config.DEFAULT_CONFIG,
            "india_news_feeds": [{"name": "Example India", "url": "https://example.com/rss"}],
            "global_india_news_article_limit": 10,
        }
    )
    response = MagicMock()
    response.text = RSS
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.india_news.requests.get", return_value=response):
        result = fetch_global_india_news()

    assert "RBI holds repo rate" in result
    assert "Reliance Industries Q1 results" not in result


@pytest.mark.unit
def test_fetch_global_india_news_does_not_match_acronyms_as_substrings():
    """Found live 2026-08-25: 'NSE' matched inside 'immense' (a CSR/PR
    story about Adani, unrelated to the exchange), because a 3-letter
    acronym is a substring of plenty of ordinary English words. Must be a
    real word-boundary match, not containment."""
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Adani sets up computer lab at Ayodhya gurukul</title>
      <description>To have been able to fulfill even a small wish of theirs brings us immense joy.</description>
      <link>https://example.com/adani-csr</link>
      <pubDate>Mon, 01 Jun 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>NSE extends trading hours for equity derivatives</title>
      <description>The exchange announced a phased rollout starting next quarter.</description>
      <link>https://example.com/nse-hours</link>
      <pubDate>Mon, 01 Jun 2026 11:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
    set_config(
        {
            **default_config.DEFAULT_CONFIG,
            "india_news_feeds": [{"name": "Example India", "url": "https://example.com/rss"}],
            "global_india_news_article_limit": 10,
        }
    )
    response = MagicMock()
    response.text = rss
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.india_news.requests.get", return_value=response):
        result = fetch_global_india_news()

    assert "NSE extends trading hours" in result
    assert "Adani sets up computer lab" not in result


@pytest.mark.unit
def test_get_global_news_vendor_wrapper_delegates_to_fetch_global_india_news():
    """india_rss's get_global_news is a thin vendor-interface wrapper --
    registered in interface.py's VENDOR_METHODS. Not the
    tool_vendors.get_global_news default as of 2026-08-25 (that reverted to
    yfinance directly, capped by a lower global_news_article_limit instead
    -- see default_config.py's history comment there), but still available
    for a config that wants it explicitly."""
    set_config(
        {
            **default_config.DEFAULT_CONFIG,
            "india_news_feeds": [{"name": "Example India", "url": "https://example.com/rss"}],
            "global_india_news_article_limit": 5,
        }
    )
    response = MagicMock()
    response.text = RSS
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.india_news.requests.get", return_value=response):
        # curr_date/look_back_days accepted but unused -- RSS feeds carry no
        # historical window, same as fetch_global_india_news's own callers.
        result = india_rss_get_global_news("2026-08-25", look_back_days=7, limit=5)

    assert "RBI holds repo rate" in result
    assert "Reliance Industries Q1 results" not in result


@pytest.mark.unit
def test_repeated_calls_with_same_feeds_hit_network_once():
    # fetch_ticker_india_news + fetch_global_india_news for the same
    # configured feeds must share one cached RSS fetch, not two — every
    # sibling fetcher (stocktwits, reddit, india_insider) caches; this one
    # didn't until now.
    set_config(
        {
            **default_config.DEFAULT_CONFIG,
            "india_news_feeds": [{"name": "Example India", "url": "https://example.com/rss"}],
        }
    )
    response = MagicMock()
    response.text = RSS
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.india_news.requests.get", return_value=response) as mock_get:
        fetch_ticker_india_news("RELIANCE.NS")
        fetch_ticker_india_news("TCS.NS")
        fetch_global_india_news()

    mock_get.assert_called_once()


@pytest.mark.unit
def test_different_feed_config_busts_the_cache():
    response = MagicMock()
    response.text = RSS
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.india_news.requests.get", return_value=response) as mock_get:
        set_config({**default_config.DEFAULT_CONFIG, "india_news_feeds": [{"name": "A", "url": "https://a.example.com/rss"}]})
        fetch_global_india_news()
        set_config({**default_config.DEFAULT_CONFIG, "india_news_feeds": [{"name": "B", "url": "https://b.example.com/rss"}]})
        fetch_global_india_news()

    assert mock_get.call_count == 2
