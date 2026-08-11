from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.finnhub_news import get_news as get_finnhub_news
from tradingagents.dataflows.gdelt_news import get_global_news as get_gdelt_global_news
from tradingagents.dataflows.alpha_vantage_news import get_global_news as get_alpha_global_news


@pytest.mark.unit
def test_finnhub_news_formats_company_articles(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    response = MagicMock()
    response.json.return_value = [
        {
            "headline": "Nvidia expands AI platform",
            "source": "Reuters",
            "summary": "Demand remains strong.",
            "url": "https://example.com/nvda",
            "datetime": 1780315200,
        }
    ]
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.finnhub_news.requests.get", return_value=response):
        result = get_finnhub_news("NVDA", "2026-06-01", "2026-06-02")

    assert "NVDA News from Finnhub" in result
    assert "Nvidia expands AI platform" in result
    assert "source: Reuters" in result


@pytest.mark.unit
def test_gdelt_global_news_uses_configured_queries():
    response = MagicMock()
    response.json.return_value = {
        "articles": [
            {
                "title": "Global markets rise",
                "domain": "example.com",
                "url": "https://example.com/markets",
                "seendate": "20260602T120000Z",
                "language": "English",
            }
        ]
    }
    response.raise_for_status.return_value = None

    with patch("tradingagents.dataflows.gdelt_news.requests.get", return_value=response) as request:
        result = get_gdelt_global_news("2026-06-02", look_back_days=1, limit=3)

    params = request.call_args.kwargs["params"]
    assert "RBI monetary policy repo rate India interest rates" in params["query"]
    assert params["startdatetime"] == "20260601000000"
    assert params["enddatetime"] == "20260602235959"
    assert "Global markets rise" in result


@pytest.mark.unit
def test_alpha_vantage_global_news_accepts_none_defaults():
    with patch("tradingagents.dataflows.alpha_vantage_news._make_api_request", return_value="ok") as request:
        result = get_alpha_global_news("2026-06-02", None, None)

    assert result == "ok"
    params = request.call_args.args[1]
    assert params["time_from"] == "20260526T0000"
    assert params["time_to"] == "20260602T0000"
    assert params["limit"] == "20"
