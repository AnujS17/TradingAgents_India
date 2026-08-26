"""Guard for api.news_sources's citation parser.

The parser recovers structure from text that news_analyst.py and
sentiment_analyst.py already embed verbatim in their reports (the
pre-fetched article blocks). These fixtures are copied from the real
heading shape each vendor's ``_format_articles``/``format_articles``
emits (tradingagents/dataflows/rss.py, gdelt_news.py, india_news.py,
finnhub_news.py, yfinance_news.py, alpha_vantage_news.py) so a format
drift in any of them is caught here, not silently in production.
"""

import pytest

from api.news_sources import extract_news_sources
from api.schemas import Reports

_STANDARD_VENDOR_BLOCK = """## Pre-Fetched Company News Used

## SIEMENS.NS News from Google News, from 2026-07-10 to 2026-08-10
### Siemens India wins large order from state utility (source: Moneycontrol, 2026-08-08)
The order covers grid automation equipment across three states.
Link: https://example.com/siemens-order

### Siemens India Q3 profit rises 18% YoY (source: Economic Times, 2026-08-05)
Profit growth was driven by industrial automation demand.
Link: https://example.com/siemens-q3

## Pre-Fetched Global News Used

No global news available.

## News Analyst Report

The company posted strong Q3 numbers, with the order win from a state
utility (source: Moneycontrol, 2026-08-08) reinforcing the demand picture.
### This looks like a heading but is inside analyst prose (source: Nobody, 2026-01-01)
Link: https://should-not-be-parsed.example.com
"""

_YFINANCE_NO_DATE_BLOCK = """## Pre-Fetched Company News Used

## TCS.NS News from Yahoo Finance
### TCS announces buyback (source: Yahoo Finance)
Link: https://example.com/tcs-buyback

## News Analyst Report

Buyback announced.
"""

_NO_ARTICLES_BLOCK = """## Pre-Fetched Company News Used

No Google News articles found for TCS.NS between 2026-07-10 and 2026-08-10

## News Analyst Report

No notable news this period.
"""

# No "## News Analyst Report" / "## Sentiment Analyst Report" boundary at
# all — just raw, unstructured prose, as if the report string were somehow
# missing the heading both analyst nodes are supposed to always emit.
_NO_BOUNDARY_HEADING = """The company had a mixed quarter. Analysts remain
split on the outlook, with some citing margin pressure and others pointing
to volume growth as a stabilising factor going into the next quarter.
"""

_COMMA_IN_SOURCE_NAME_BLOCK = """## Pre-Fetched Company News Used

## TCS.NS News from Yahoo Finance
### Deal signed (source: Dow Jones, Inc.)
Link: https://example.com/deal

## News Analyst Report

Deal signed.
"""


@pytest.mark.unit
def test_parses_standard_vendor_heading_shape():
    reports = Reports(news=_STANDARD_VENDOR_BLOCK)

    sources = extract_news_sources(reports)

    assert len(sources) == 2
    first = sources[0]
    assert first.title == "Siemens India wins large order from state utility"
    assert first.source == "Moneycontrol"
    assert first.published_date == "2026-08-08"
    assert first.url == "https://example.com/siemens-order"
    assert "grid automation" in (first.snippet or "")

    # The LAST article in a block sits right before the next section's
    # "## ..." heading — regression guard for a real bug caught during
    # planning: that trailing section heading must never leak into this
    # article's snippet.
    second = sources[1]
    assert second.snippet == "Profit growth was driven by industrial automation demand."
    assert "Pre-Fetched Global News Used" not in (second.snippet or "")


@pytest.mark.unit
def test_never_parses_text_after_the_analyst_report_heading():
    reports = Reports(news=_STANDARD_VENDOR_BLOCK)

    sources = extract_news_sources(reports)

    assert all(s.source != "Nobody" for s in sources)
    assert len(sources) == 2  # not 3 — the prose-embedded fake heading is excluded


@pytest.mark.unit
def test_parses_yfinance_heading_with_no_date():
    reports = Reports(news=_YFINANCE_NO_DATE_BLOCK)

    sources = extract_news_sources(reports)

    assert len(sources) == 1
    assert sources[0].title == "TCS announces buyback"
    assert sources[0].source == "Yahoo Finance"
    assert sources[0].published_date is None


@pytest.mark.unit
def test_returns_empty_list_when_no_articles_present():
    reports = Reports(news=_NO_ARTICLES_BLOCK)

    assert extract_news_sources(reports) == []


@pytest.mark.unit
def test_returns_empty_list_for_missing_reports():
    assert extract_news_sources(Reports()) == []


@pytest.mark.unit
def test_dedupes_the_same_article_across_news_and_sentiment_reports():
    reports = Reports(news=_STANDARD_VENDOR_BLOCK, sentiment=_STANDARD_VENDOR_BLOCK)

    sources = extract_news_sources(reports)

    assert len(sources) == 2  # not 4 — same (title, source) pairs, deduped


@pytest.mark.unit
def test_fails_closed_when_no_boundary_heading_is_present():
    """Pins the fail-closed behavior: a report string missing the
    '## News Analyst Report' / '## Sentiment Analyst Report' boundary must
    yield zero citations, not fall back to scanning the whole raw string
    (which could include the model's own prose). Today every persisted
    report has the heading, but that must not be the only thing keeping
    this safe."""
    reports = Reports(news=_NO_BOUNDARY_HEADING)

    assert extract_news_sources(reports) == []


_GLOBAL_AND_INDIA_BLOCKS = """## Pre-Fetched Company News Used

## SIEMENS.NS News from Google News, from 2026-07-10 to 2026-08-10
### Siemens India wins large order from state utility (source: Moneycontrol, 2026-08-08)
The order covers grid automation equipment across three states.
Link: https://example.com/siemens-order

## Pre-Fetched Global News Used

## Global Market News from GDELT, from 2026-08-03 to 2026-08-10
### Oil prices tick back up as war risk reignites (source: Yahoo Finance, 2026-08-09)
Crude climbed on renewed Middle East tension.
Link: https://example.com/oil-prices

## Pre-Fetched India-Market News Used

## Supplemental Global India News
### Sun Pharma's recall of eyedrops: Experts raise concerns (source: Business Line, 2026-08-23)
Unrelated to Siemens.
Link: https://example.com/sun-pharma-recall

## Pre-Fetched Exchange Filings Used

No filings.

## News Analyst Report

Siemens posted strong numbers this quarter.
"""


@pytest.mark.unit
def test_global_and_india_market_sections_are_excluded_from_news_report():
    """The whole point: these sections are ticker-agnostic market/macro
    backdrop, given to the model but not evidence about the company being
    analysed, so they must never surface as a "source" for this run."""
    reports = Reports(news=_GLOBAL_AND_INDIA_BLOCKS)

    sources = extract_news_sources(reports)

    assert len(sources) == 1
    assert sources[0].title == "Siemens India wins large order from state utility"
    assert all("Oil prices" not in s.title for s in sources)
    assert all("Sun Pharma" not in s.title for s in sources)


@pytest.mark.unit
def test_comma_in_source_name_does_not_corrupt_published_date():
    """Real data-corruption case: on the no-date (yfinance) heading shape,
    a publisher name containing a comma (e.g. 'Dow Jones, Inc.') must not
    be misparsed as source='Dow Jones' / published_date='Inc.'."""
    reports = Reports(news=_COMMA_IN_SOURCE_NAME_BLOCK)

    sources = extract_news_sources(reports)

    assert len(sources) == 1
    assert sources[0].source == "Dow Jones, Inc."
    assert sources[0].published_date is None
