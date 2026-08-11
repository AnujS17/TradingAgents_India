from unittest.mock import MagicMock, patch

import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows import india_news
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.india_news import fetch_global_india_news, fetch_ticker_india_news


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
