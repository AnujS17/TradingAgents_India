"""Google News RSS search vendor tests.

This is the only company-news source in the pipeline that is a genuine search
(arbitrary query + explicit date range) rather than a capped feed or a
throttled API. Measured 2026-08-11: 71 articles for "Laurus Labs" and 100 for
"Tata Motors Passenger Vehicles" over 30 days, against the single competitor
story (about Mahindra) that Yahoo returned for TMPV.NS.
"""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.company_names import clear_caches
from tradingagents.dataflows.google_news import (
    _build_query,
    _drop_redundant_summary,
    _is_latin_script,
    clear_cache,
    get_news,
)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Tata Motors PV sales rise 59% to 63,760 units in July - BusinessLine</title>
    <description>Tata Motors PV sales rise 59% to 63,760 units in July BusinessLine</description>
    <link>https://news.google.com/rss/articles/abc</link>
    <pubDate>Sat, 01 Aug 2026 06:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Old story well outside the window - Mint</title>
    <description>Old story</description>
    <link>https://news.google.com/rss/articles/def</link>
    <pubDate>Wed, 01 Jan 2025 06:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


@pytest.fixture(autouse=True)
def _reset():
    clear_cache()
    clear_caches()
    yield
    clear_cache()
    clear_caches()


@pytest.fixture
def stub_name(monkeypatch):
    def _apply(name):
        monkeypatch.setattr(
            "tradingagents.dataflows.company_names.resolve_company_name",
            lambda ticker: name,
        )
        clear_caches()
        clear_cache()
    return _apply


def _response(text=RSS):
    r = MagicMock()
    r.text = text
    r.raise_for_status.return_value = None
    return r


@pytest.mark.unit
def test_query_uses_explicit_date_range(stub_name):
    # after:/before: is used instead of the relative when:30d form so the
    # caller's exact window is honoured rather than approximated.
    stub_name("Tata Motors Passenger Vehicles Limited")
    q = _build_query("TMPV.NS", "2026-07-12", "2026-08-11")

    assert "after:2026-07-12" in q
    assert "before:2026-08-11" in q


@pytest.mark.unit
def test_query_searches_company_name_not_suffixed_ticker(stub_name):
    stub_name("Tata Motors Passenger Vehicles Limited")
    q = _build_query("TMPV.NS", "2026-07-12", "2026-08-11")

    assert '"Tata Motors Passenger Vehicles"' in q
    assert ".NS" not in q


@pytest.mark.unit
def test_articles_are_returned_and_publisher_attributed(stub_name):
    stub_name("Tata Motors Passenger Vehicles Limited")
    with patch("tradingagents.dataflows.google_news.requests.get", return_value=_response()):
        out = get_news("TMPV.NS", "2026-07-12", "2026-08-11")

    assert "Tata Motors PV sales rise 59%" in out
    # Publisher must move from the title into the source, or every article is
    # attributed to "Google News" and the real outlet is buried in the headline.
    assert "BusinessLine via Google News" in out
    assert "- BusinessLine (source" not in out


@pytest.mark.unit
def test_articles_outside_the_window_are_dropped(stub_name):
    stub_name("Tata Motors Passenger Vehicles Limited")
    with patch("tradingagents.dataflows.google_news.requests.get", return_value=_response()):
        out = get_news("TMPV.NS", "2026-07-12", "2026-08-11")

    assert "Old story well outside the window" not in out


@pytest.mark.unit
def test_network_failure_degrades_to_error_string(stub_name):
    # Must return a fallback-triggering string, not raise: route_to_vendor
    # needs to move on to the next vendor.
    stub_name("Tata Motors Passenger Vehicles Limited")
    with patch("tradingagents.dataflows.google_news.requests.get", side_effect=OSError("boom")):
        out = get_news("TMPV.NS", "2026-07-12", "2026-08-11")

    assert out.lower().startswith("error")


@pytest.mark.unit
def test_repeated_calls_hit_network_once(stub_name):
    stub_name("Tata Motors Passenger Vehicles Limited")
    with patch("tradingagents.dataflows.google_news.requests.get", return_value=_response()) as mock_get:
        get_news("TMPV.NS", "2026-07-12", "2026-08-11")
        get_news("TMPV.NS", "2026-07-12", "2026-08-11")

    mock_get.assert_called_once()


@pytest.mark.unit
def test_redundant_summary_is_blanked():
    # Google's RSS description is the headline plus publisher, not an
    # abstract; repeating it wastes prompt budget on every article.
    article = {"title": "Tata Motors PV sales rise 59%", "summary": "Tata Motors PV sales rise 59% BusinessLine"}
    _drop_redundant_summary(article)

    assert article["summary"] == ""


@pytest.mark.unit
def test_real_summary_is_preserved():
    article = {"title": "Tata Motors PV sales rise", "summary": "Volumes hit 63,760 units, EV mix doubled."}
    _drop_redundant_summary(article)

    assert article["summary"].startswith("Volumes hit")


@pytest.mark.unit
@pytest.mark.parametrize(
    "title,expected",
    [
        ("Tata Motors PV sales rise 59%", True),
        ("Tata Motors introduces offers of up to ₹2.25 lakh", True),  # ₹ must not disqualify
        ("டாடா குழுமத்திற்கு மேற்கு வங்க மாநிலத்தின் அழைப்பு", False),
        ("", True),
    ],
)
def test_regional_language_headlines_are_filtered(title, expected):
    assert _is_latin_script(title) is expected
