from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.finnhub_news import get_news as get_finnhub_news
from tradingagents.dataflows.gdelt_news import get_global_news as get_gdelt_global_news
from tradingagents.dataflows.alpha_vantage_news import get_global_news as get_alpha_global_news
from tradingagents.dataflows.alpha_vantage_news import get_news as get_alpha_company_news


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
    assert '"RBI repo rate"' in params["query"]
    assert '"Nifty 50"' in params["query"]
    assert params["startdatetime"] == "20260601000000"
    assert params["enddatetime"] == "20260602235959"
    assert "Global markets rise" in result


@pytest.mark.unit
def test_alpha_vantage_global_news_accepts_none_defaults():
    import json

    raw = json.dumps(
        {
            "feed": [
                {
                    "title": "Fed signals rate pause",
                    "source": "Kalkine Media",
                    "summary": "Markets rallied on the dovish tone.",
                    "url": "https://example.com/fed-pause",
                    "time_published": "20260602T140000",
                }
            ]
        }
    )
    with patch("tradingagents.dataflows.alpha_vantage_news._make_api_request", return_value=raw) as request:
        result = get_alpha_global_news("2026-06-02", None, None)

    params = request.call_args.args[1]
    assert params["time_from"] == "20260526T0000"
    assert params["time_to"] == "20260602T0000"
    assert params["limit"] == "5"

    # The actual point: formatted into the standard heading shape every
    # other vendor uses, not NEWS_SENTIMENT's raw JSON (see
    # alpha_vantage_news.py's _format_articles docstring for why this
    # matters now that alpha_vantage is the primary get_global_news vendor).
    assert "Fed signals rate pause" in result
    assert "source: Kalkine Media, 2026-06-02" in result
    assert "Link: https://example.com/fed-pause" in result


@pytest.mark.unit
def test_alpha_vantage_company_news_is_formatted_not_raw_json():
    import json

    raw = json.dumps(
        {
            "feed": [
                {
                    "title": "Siemens India wins large order",
                    "source": "Moneycontrol",
                    "summary": "Grid automation equipment across three states.",
                    "url": "https://example.com/siemens-order",
                    "time_published": "20260808T090000",
                }
            ]
        }
    )
    with patch("tradingagents.dataflows.alpha_vantage_news._make_api_request", return_value=raw):
        result = get_alpha_company_news("SIEMENS.NS", "2026-07-10", "2026-08-10")

    assert "SIEMENS.NS News from Alpha Vantage" in result
    assert "Siemens India wins large order" in result
    assert "source: Moneycontrol, 2026-08-08" in result
    assert "Link: https://example.com/siemens-order" in result


@pytest.mark.unit
def test_alpha_vantage_news_degrades_gracefully_on_malformed_response():
    """Fail open to an empty article list, not a crash, for a rate-limit
    payload or malformed body that slipped past _make_api_request's own
    check (see alpha_vantage_news.py's _parse_feed docstring)."""
    with patch("tradingagents.dataflows.alpha_vantage_news._make_api_request", return_value="not json"):
        result = get_alpha_global_news("2026-06-02", 7, 5)

    assert "No Alpha Vantage global news found" in result
